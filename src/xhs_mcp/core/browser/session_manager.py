"""Browser instance management layer.

Entry points — the CLI, the MCP stdio server, the MCP HTTP server — never
create a browser themselves. They ask this layer for the instance belonging to
a profile, and it enforces one invariant:

    one profile directory == one browser instance

both *within* a process and *across* processes. Everything above this layer can
change shape (new entry points, new transports, merged code paths) without the
browser layer noticing, and everything below it can assume it is the only
browser for that profile.

Cross-process sharing works through Chromium's own mechanism: a browser
launched with a remote debugging port writes ``DevToolsActivePort`` into its
profile directory. A second process reads that file and attaches over CDP
instead of launching, which is what makes "one profile, one instance" hold even
when the MCP server and a CLI command run side by side. Whoever launched the
browser owns it and closes it; anyone who attached merely disconnects, so a
short-lived CLI command can never kill a long-running server's browser.

There is deliberately no switch to turn this off. The invariant is the point of
this layer, and disabling sharing could only ever turn a working setup into a
profile-lock failure. Callers that genuinely want an isolated browser ask for it
the meaningful way: a different ``XHS_USER_DATA_DIR``.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from cloakbrowser import launch_persistent_context_async
from playwright.async_api import BrowserContext, async_playwright

from ...shared.errors import BrowserLaunchError
from ...shared.logger import logger
from ...shared.profile import ensure_user_data_dir

_DEVTOOLS_PORT_FILE = "DevToolsActivePort"

# Port 0 lets the OS pick a free port; Chromium records it in the profile.
_DEBUG_PORT_ARG = "--remote-debugging-port=0"

_ATTACH_PROBE_TIMEOUT = 2.0

_LAUNCH_RACE_RETRIES = 3
_LAUNCH_RACE_DELAY = 0.75


def _humanize_enabled() -> bool:
    """Human-like mouse curves, key timing and scrolling.

    On by default: behavioural signals are what a fingerprint patch cannot
    cover. It is not free — typing runs about 1.25s per character, which is why
    publishing goes through the task queue rather than a blocking tool call.
    Set ``XHS_HUMANIZE=false`` to trade realism back for speed.
    """
    return os.environ.get("XHS_HUMANIZE", "true").strip().lower() != "false"


def _is_profile_lock_error(error: BaseException) -> bool:
    text = str(error)
    return (
        "ProcessSingleton" in text
        or "SingletonLock" in text
        or "profile appears to be in use" in text.lower()
        or "already running" in text.lower()
    )


def read_devtools_endpoint(profile_dir: str) -> str | None:
    """Return the CDP HTTP endpoint of a browser running on ``profile_dir``.

    The file can outlive a crashed browser, so the caller still has to probe it.
    """
    port_file = Path(profile_dir) / _DEVTOOLS_PORT_FILE

    if not port_file.exists():
        return None

    try:
        first_line = port_file.read_text(encoding="utf-8").splitlines()[0].strip()
        port = int(first_line)
    except (OSError, ValueError, IndexError):
        return None

    if port <= 0:
        return None

    return f"http://127.0.0.1:{port}"


async def _endpoint_is_live(endpoint: str) -> bool:
    """Check the recorded endpoint actually answers, filtering out stale files."""
    try:
        async with httpx.AsyncClient(timeout=_ATTACH_PROBE_TIMEOUT) as client:
            response = await client.get(f"{endpoint}/json/version")
            return response.status_code == 200
    except Exception:
        return False


@dataclass
class BrowserSession:
    """A single browser instance, shared by every caller using its profile."""

    context: BrowserContext
    profile_dir: str
    owns_browser: bool
    """True when this process launched it, and is therefore the one to close it."""

    playwright: Any = None
    browser: Any = None
    ref_count: int = 0
    unclaimed_pages: list[Any] = field(default_factory=list)
    """Pages that existed at launch, handed out before opening new tabs."""

    async def shutdown(self) -> None:
        if self.owns_browser:
            # CloakBrowser patches close() to stop its Playwright instance too.
            await self.context.close()
            return

        # Attached: drop the CDP connection and leave the browser running for
        # whoever owns it.
        if self.browser is not None:
            await self.browser.close()
        if self.playwright is not None:
            await self.playwright.stop()


class BrowserSessionManager:
    """Creates or attaches to browser instances, one per profile directory."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, profile_dir: str) -> asyncio.Lock:
        if profile_dir not in self._locks:
            self._locks[profile_dir] = asyncio.Lock()
        return self._locks[profile_dir]

    async def acquire(
        self, profile_dir: str, headless: bool, extra_args: list[str] | None = None
    ) -> BrowserSession:
        """Return the browser instance for ``profile_dir``, creating it if needed."""
        async with self._lock_for(profile_dir):
            existing = self._sessions.get(profile_dir)
            if existing is not None:
                existing.ref_count += 1
                logger.debug(
                    f"Reusing browser instance for {profile_dir} "
                    f"(refs={existing.ref_count})"
                )
                return existing

            session = await self._open(profile_dir, headless, extra_args or [])
            session.ref_count = 1
            self._sessions[profile_dir] = session
            return session

    async def release(self, profile_dir: str) -> None:
        """Drop one reference, shutting the instance down when the last one goes."""
        async with self._lock_for(profile_dir):
            session = self._sessions.get(profile_dir)
            if session is None:
                return

            session.ref_count -= 1
            if session.ref_count > 0:
                logger.debug(
                    f"Released browser instance for {profile_dir} "
                    f"(refs={session.ref_count})"
                )
                return

            self._sessions.pop(profile_dir, None)
            try:
                await session.shutdown()
            except Exception as error:
                logger.warn(f"Error shutting down browser instance: {error}")

    async def shutdown_all(self) -> None:
        """Drop every instance this process holds, whatever the reference counts.

        This is the teardown entry points call on their way out: the process is
        going away, so its references go with it. Ownership still decides what
        that means — an instance this process launched is closed, one it merely
        attached to is disconnected from and left running for its owner.
        """
        for profile_dir in list(self._sessions):
            session = self._sessions.pop(profile_dir, None)
            if session is None:
                continue
            try:
                await session.shutdown()
            except Exception as error:
                logger.warn(f"Error shutting down browser instance: {error}")

    async def _open(
        self, profile_dir: str, headless: bool, extra_args: list[str]
    ) -> BrowserSession:
        """Attach to a running browser for this profile, or launch one."""
        attached = await self._try_attach(profile_dir)
        if attached is not None:
            return attached

        last_error: BaseException | None = None

        for attempt in range(_LAUNCH_RACE_RETRIES):
            try:
                return await self._launch(profile_dir, headless, extra_args)
            except Exception as error:
                last_error = error

                if not _is_profile_lock_error(error):
                    break

                # Another process won the race and is starting the browser this
                # profile is supposed to have. Give it a moment, then attach.
                logger.debug(
                    f"Profile {profile_dir} was claimed by another process "
                    f"(attempt {attempt + 1}); waiting to attach"
                )
                await asyncio.sleep(_LAUNCH_RACE_DELAY)

                attached = await self._try_attach(profile_dir)
                if attached is not None:
                    return attached

        assert last_error is not None
        raise BrowserLaunchError(
            self._launch_error_message(last_error, profile_dir),
            {"headless": headless, "userDataDir": profile_dir},
            last_error,
        ) from last_error

    async def _try_attach(self, profile_dir: str) -> BrowserSession | None:
        endpoint = read_devtools_endpoint(profile_dir)
        if endpoint is None:
            return None

        if not await _endpoint_is_live(endpoint):
            logger.debug(f"Stale DevToolsActivePort for {profile_dir}; ignoring")
            return None

        playwright = None
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(endpoint)

            if not browser.contexts:
                await browser.close()
                await playwright.stop()
                return None

            logger.info(
                f"Attached to the browser already running on {profile_dir} "
                f"({endpoint}) instead of launching a second one"
            )
            return BrowserSession(
                context=browser.contexts[0],
                profile_dir=profile_dir,
                owns_browser=False,
                playwright=playwright,
                browser=browser,
            )
        except Exception as error:
            logger.debug(f"Could not attach to {endpoint}: {error}")
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass
            return None

    async def _launch(
        self, profile_dir: str, headless: bool, extra_args: list[str]
    ) -> BrowserSession:
        ensure_user_data_dir(profile_dir)

        # Makes this instance discoverable, so later processes attach instead of
        # failing on the profile lock. Verified not to change the browser's
        # fingerprint.
        args = [*extra_args, _DEBUG_PORT_ARG]

        humanize = _humanize_enabled()
        logger.debug(
            f"Launching browser instance for {profile_dir} (humanize={humanize})"
        )
        context = await launch_persistent_context_async(
            user_data_dir=profile_dir,
            headless=headless,
            args=args or None,
            humanize=humanize,
        )

        return BrowserSession(
            context=context,
            profile_dir=profile_dir,
            owns_browser=True,
            # A persistent context starts with a blank page; hand it out before
            # opening new tabs so headed runs show a single window.
            unclaimed_pages=list(context.pages),
        )

    @staticmethod
    def _launch_error_message(error: BaseException, profile_dir: str) -> str:
        if _is_profile_lock_error(error):
            return (
                f"Failed to launch browser: the profile directory {profile_dir} is "
                f"held by another process, and attaching to that browser did not "
                f"succeed either. It may be shutting down — retry in a moment, or "
                f"give this process its own XHS_USER_DATA_DIR. "
                f"Original error: {error}"
            )

        return f"Failed to launch browser: {error}"


_session_manager = BrowserSessionManager()


def get_session_manager() -> BrowserSessionManager:
    """The process-wide instance manager every entry point goes through."""
    return _session_manager
