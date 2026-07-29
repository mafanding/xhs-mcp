"""Browser Manager for XHS Operations.

Backed by CloakBrowser, which hands back ordinary Playwright objects driven by a
stealth-patched Chromium binary.

This is the *browser layer*: pages, navigation, waiting, cookies. It never
launches a browser itself — :mod:`xhs_mcp.core.browser.session_manager` owns
that, so the "one profile, one browser instance" invariant holds no matter
which entry point is driving.

Three differences from the Puppeteer original are worth knowing about:

Session storage
    The original re-injected ``cookies.json`` into a fresh, incognito-like
    context on every run — a strong automation signal, since a real user's
    browser is never a brand-new private window. The session now lives in a
    persistent Chromium profile that the browser maintains itself, so nothing
    here saves cookies. A legacy cookie file is imported once and retired.

``browser_path``
    CloakBrowser always launches its own patched binary — ``executable_path`` is
    set internally and is not a parameter of any ``launch_*`` function. The
    ``browser_path`` / ``-b`` / ``executablePath`` argument is therefore accepted
    everywhere it was accepted before, for interface compatibility, but has no
    effect. Pointing this at a stock Chrome would defeat the stealth patches
    that motivate using CloakBrowser at all.

Chromium flags
    The original passed a Puppeteer hardening set (``--disable-gpu``,
    ``--no-sandbox``, ``--no-zygote``, …). Several of those are bot tells that
    would undo CloakBrowser's fingerprint work, so the stealth defaults are used
    instead. Set ``XHS_BROWSER_ARGS`` (comma-separated) to append flags — e.g.
    ``--no-sandbox`` when running as root in a container.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ...shared.config import get_config
from ...shared.cookies import delete_cookies_file, has_legacy_cookies, load_cookies
from ...shared.errors import BrowserNavigationError, XHSError
from ...shared.logger import logger
from ...shared.types import Config, Cookie
from ...shared.utils import sleep
from .browser_pool_service import BrowserPoolService
from .browser_types import BrowserPoolOptions, ManagedBrowser
from .session_manager import BrowserSession, get_session_manager

# Keys Playwright's add_cookies() accepts. A cookie file written by the
# Puppeteer version also carries size/session/sourceScheme/partitionKey, which
# Playwright rejects outright, so anything outside this set is dropped on load.
_PLAYWRIGHT_COOKIE_KEYS = (
    "name",
    "value",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
)

_VALID_SAME_SITE = ("Strict", "Lax", "None")

WaitUntil = str

# Puppeteer's networkidle0/networkidle2 both collapse to Playwright's networkidle.
_WAIT_UNTIL_MAP = {
    "load": "load",
    "domcontentloaded": "domcontentloaded",
    "networkidle0": "networkidle",
    "networkidle2": "networkidle",
    "networkidle": "networkidle",
    "commit": "commit",
}


def _now_ms() -> float:
    return time.time() * 1000


def _extra_browser_args() -> list[str]:
    raw = os.environ.get("XHS_BROWSER_ARGS", "").strip()
    if not raw:
        return []
    return [arg.strip() for arg in raw.split(",") if arg.strip()]


def to_playwright_cookies(cookies: list[Cookie]) -> list[dict[str, Any]]:
    """Filter stored cookies down to the keys Playwright accepts."""
    result: list[dict[str, Any]] = []

    for cookie in cookies:
        converted = {
            key: cookie[key]  # type: ignore[literal-required]
            for key in _PLAYWRIGHT_COOKIE_KEYS
            if cookie.get(key) is not None  # type: ignore[union-attr]
        }

        same_site = converted.get("sameSite")
        if same_site not in _VALID_SAME_SITE:
            converted.pop("sameSite", None)

        if converted.get("name") is None or converted.get("value") is None:
            continue

        if not converted.get("domain") or not converted.get("path"):
            continue

        result.append(converted)

    return result


class BrowserManager:
    """Owns the browser context, page lifecycle, navigation and cookie plumbing."""

    def __init__(
        self,
        config: Config | None = None,
        use_pool: bool = False,
        pool_options: BrowserPoolOptions | None = None,
    ) -> None:
        self.config = config or get_config()
        self._session: BrowserSession | None = None
        self._context: BrowserContext | None = None
        self._browser_pool: BrowserPoolService | None = None
        self._use_pool = use_pool
        self._pool_options = pool_options
        # Page -> creation time in ms. Concurrent operations each hold a tab, so
        # leak detection has to tell a long-lived leak from legitimate traffic.
        self._tracked_pages: dict[Page, float] = {}
        self._max_tracked_pages = 10
        self._stale_page_age = 300_000  # 5 minutes
        # A persistent context opens with one page already attached; reuse it
        # for the first create_page() so headed runs show a single window.
        self._pending_initial_page: Page | None = None
        self._launch_lock = asyncio.Lock()

        if self._use_pool:
            self._browser_pool = BrowserPoolService(self.config, pool_options)

    # ------------------------------------------------------------------
    # Page lifecycle
    # ------------------------------------------------------------------

    async def create_page(
        self,
        headless: bool | None = None,
        executable_path: str | None = None,
        should_load_cookies: bool = True,
    ) -> Page:
        """Create a page, launching the browser on first use.

        The browser is cached, so — exactly as in the original — the ``headless``
        value of the *first* call decides the mode for this manager's whole
        lifetime; later calls reuse the existing browser and ignore their own
        ``headless`` argument.
        """
        try:
            if self._use_pool and self._browser_pool:
                return await self._create_page_from_pool(should_load_cookies)

            if self._context is None:
                # Serialise the launch. Concurrent callers would otherwise each
                # start a browser against the same profile directory, and all
                # but one would fail on Chromium's ProcessSingleton lock.
                async with self._launch_lock:
                    if self._context is None:
                        self._context = await self._launch_context(
                            headless, executable_path
                        )

            page = self._take_initial_page() or await self._context.new_page()

            self._tracked_pages[page] = _now_ms()
            page.once("close", lambda _: self._tracked_pages.pop(page, None))

            # Leak detection: something is not closing its pages.
            if len(self._tracked_pages) > self._max_tracked_pages:
                await self._close_stale_pages()

            page.set_default_timeout(self.config.browser.default_timeout)
            page.set_default_navigation_timeout(self.config.browser.navigation_timeout)

            if should_load_cookies:
                await self._migrate_legacy_cookies(page.context)

            return page
        except XHSError:
            raise
        except Exception as error:
            logger.error(f"Browser page creation error: {error}")
            raise self._handle_browser_error(error, "create_page") from error

    async def _create_page_from_pool(self, should_load_cookies: bool = True) -> Page:
        if self._browser_pool is None:
            raise XHSError("Browser pool not initialized", "BrowserPoolError")

        managed_browser = await self._browser_pool.acquire_browser()

        try:
            page = await managed_browser.context.new_page()

            page.set_default_timeout(self.config.browser.default_timeout)
            page.set_default_navigation_timeout(self.config.browser.navigation_timeout)

            if should_load_cookies:
                await self._migrate_legacy_cookies(page.context)

            released = False

            def release_browser(_: Any = None) -> None:
                nonlocal released
                if released:
                    return
                released = True
                asyncio.ensure_future(  # noqa: RUF006 - fire-and-forget release
                    self._release_quietly(managed_browser)
                )

            page.once("close", release_browser)

            return page
        except Exception:
            await self._release_quietly(managed_browser)
            raise

    async def _release_quietly(self, managed_browser: ManagedBrowser) -> None:
        try:
            if self._browser_pool is not None:
                await self._browser_pool.release_browser(managed_browser)
        except Exception as error:
            logger.warn(f"Error releasing browser back to pool: {error}")

    def _take_initial_page(self) -> Page | None:
        """Hand out the persistent context's pre-opened page exactly once."""
        page = self._pending_initial_page
        self._pending_initial_page = None

        if page is not None and not page.is_closed():
            return page
        return None

    async def _launch_context(
        self, headless: bool | None = None, executable_path: str | None = None
    ) -> BrowserContext:
        """Ask the instance manager for this profile's browser."""
        is_headless = (
            headless if headless is not None else self.config.browser.headless_default
        )

        if executable_path:
            logger.warn(
                "browser_path is accepted for compatibility but ignored: CloakBrowser "
                "always launches its own stealth-patched Chromium "
                f"(requested: {executable_path})"
            )

        if self.config.browser.slowmo:
            logger.warn(
                "browser.slowmo is not applied: CloakBrowser's context launcher does "
                "not forward Playwright launch options"
            )

        user_data_dir = self.config.paths.user_data_dir

        session = await get_session_manager().acquire(
            user_data_dir, is_headless, _extra_browser_args()
        )
        self._session = session

        # Only the process that launched the browser may claim its pre-opened
        # blank page. When attached, those pages belong to whoever opened them.
        if session.owns_browser and session.unclaimed_pages:
            self._pending_initial_page = session.unclaimed_pages.pop(0)

        return session.context

    # ------------------------------------------------------------------
    # Cookies
    # ------------------------------------------------------------------

    async def _migrate_legacy_cookies(self, context: BrowserContext) -> bool:
        """Seed a fresh profile from a legacy ``cookies.json``, once.

        The profile is the session store; this only exists so an installation
        that logged in under the old cookie-file scheme does not have to log in
        again. A profile that already holds cookies is left alone, and the file
        is retired after a successful import so it never gets re-applied.
        """
        try:
            if not has_legacy_cookies():
                return False

            if await context.cookies():
                logger.debug("Profile already holds cookies; skipping legacy import")
                return False

            cookies = load_cookies()
            if not cookies:
                return False

            playwright_cookies = to_playwright_cookies(cookies)
            if not playwright_cookies:
                return False

            await context.add_cookies(playwright_cookies)
            logger.info(
                f"Imported {len(playwright_cookies)} cookies from the legacy "
                f"cookies.json into the browser profile; the file is no longer used"
            )
            delete_cookies_file()
            return True
        except Exception as error:
            logger.warn(f"Failed to import legacy cookies: {error}")
            return False

    # ------------------------------------------------------------------
    # Navigation and waiting
    # ------------------------------------------------------------------

    async def navigate_with_retry(
        self,
        page: Page,
        url: str,
        wait_until: WaitUntil = "load",
        max_retries: int | None = None,
    ) -> None:
        """Navigate to ``url``, retrying only on navigation timeouts."""
        retries = max_retries if max_retries is not None else self.config.xhs.max_retries
        resolved_wait_until = _WAIT_UNTIL_MAP.get(wait_until, "load")

        for attempt in range(retries + 1):
            try:
                await page.goto(
                    url,
                    wait_until=resolved_wait_until,  # type: ignore[arg-type]
                    timeout=self.config.browser.navigation_timeout,
                )
                return
            except PlaywrightTimeoutError as error:
                if attempt == retries:
                    raise BrowserNavigationError(
                        f"Failed to navigate to {url} after {retries + 1} attempts",
                        {"url": url, "attempts": attempt + 1},
                        error,
                    ) from error

                await sleep(self.config.xhs.retry_delay * 1000)

    async def try_wait_for_selector(
        self,
        page: Page,
        selector: str,
        timeout: int | None = None,
        visible: bool = True,
    ) -> bool:
        """Wait for a selector, returning False on timeout instead of raising."""
        try:
            await page.wait_for_selector(
                selector,
                timeout=timeout or self.config.browser.default_timeout,
                # Puppeteer's `visible: false` means "present in the DOM", not
                # "hidden" — Playwright spells that "attached".
                state="visible" if visible else "attached",
            )
            return True
        except PlaywrightTimeoutError:
            return False

    async def wait_for_selector_visible(
        self, page: Page, selector: str, timeout: int | None = None
    ) -> bool:
        return await self.try_wait_for_selector(page, selector, timeout, True)

    async def wait_for_selector_hidden(
        self, page: Page, selector: str, timeout: int | None = None
    ) -> bool:
        return await self.try_wait_for_selector(page, selector, timeout, False)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    async def cleanup(self) -> None:
        if self._use_pool and self._browser_pool:
            try:
                await self._browser_pool.cleanup()
            except Exception as error:
                logger.warn(f"Error cleaning up browser pool: {error}")
            finally:
                self._browser_pool = None

        await self.close_all_pages()

        if self._session is not None:
            session = self._session
            self._session = None
            self._context = None
            try:
                # The manager shuts the instance down only when the last user
                # lets go, and an attached process just disconnects.
                await get_session_manager().release(session.profile_dir)
            except Exception as error:
                logger.warn(f"Error releasing browser instance: {error}")

    async def _close_stale_pages(self) -> None:
        """Reclaim pages that were opened long ago and never closed.

        Only pages older than ``_stale_page_age`` are touched: with several
        tabs driving operations at once, closing every tracked page would kill
        work that is legitimately in flight.
        """
        cutoff = _now_ms() - self._stale_page_age
        stale = [page for page, created in self._tracked_pages.items() if created < cutoff]

        if not stale:
            logger.warn(
                f"Tracked pages ({len(self._tracked_pages)}) exceeds threshold "
                f"({self._max_tracked_pages}), but none are stale yet - "
                f"leaving concurrent work alone"
            )
            return

        logger.warn(
            f"Tracked pages ({len(self._tracked_pages)}) exceeds threshold "
            f"({self._max_tracked_pages}), closing {len(stale)} stale page(s)"
        )

        for page in stale:
            await self._close_page_quietly(page)
            self._tracked_pages.pop(page, None)

    async def close_all_pages(self) -> None:
        """Close every page this manager opened that is still open."""
        for page in list(self._tracked_pages):
            await self._close_page_quietly(page)
        self._tracked_pages.clear()

    @staticmethod
    async def _close_page_quietly(page: Page) -> None:
        if page.is_closed():
            return
        try:
            await page.close()
        except Exception as error:
            logger.warn(f"Error closing tracked page: {error}")

    # ------------------------------------------------------------------
    # Pool controls and diagnostics
    # ------------------------------------------------------------------

    def get_browser_pool_stats(self) -> Any:
        if self._use_pool and self._browser_pool:
            return self._browser_pool.get_pool_stats()
        return None

    def get_tracked_page_count(self) -> int:
        return len(self._tracked_pages)

    def enable_browser_pool(self) -> None:
        if not self._use_pool:
            self._use_pool = True
            self._browser_pool = BrowserPoolService(self.config, self._pool_options)

    async def disable_browser_pool(self) -> None:
        if self._use_pool and self._browser_pool:
            await self._browser_pool.cleanup()
            self._browser_pool = None
            self._use_pool = False

    # ------------------------------------------------------------------
    # Error mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _handle_browser_error(error: BaseException, operation_name: str) -> XHSError:
        context = {"operationName": operation_name}

        if isinstance(error, PlaywrightTimeoutError):
            if "login" in operation_name.lower():
                return XHSError(
                    f"Login operation timed out during {operation_name}",
                    "LoginTimeoutError",
                    context,
                    error,
                )
            return XHSError(
                f"Browser operation timed out: {operation_name}",
                "BrowserError",
                context,
                error,
            )

        if "navigation" in str(error).lower():
            return BrowserNavigationError(
                f"Navigation failed during {operation_name}: {error}",
                context,
                error,
            )

        return XHSError(
            f"Browser error during {operation_name}: {error}",
            "BrowserError",
            context,
            error,
        )


_global_browser_manager: BrowserManager | None = None


def get_browser_manager(use_pool: bool = False) -> BrowserManager:
    global _global_browser_manager
    if _global_browser_manager is None:
        _global_browser_manager = BrowserManager(None, use_pool)
    return _global_browser_manager


def get_pooled_browser_manager() -> BrowserManager:
    return get_browser_manager(True)


async def cleanup_global_browser_manager() -> None:
    global _global_browser_manager
    if _global_browser_manager is not None:
        await _global_browser_manager.cleanup()
        _global_browser_manager = None
