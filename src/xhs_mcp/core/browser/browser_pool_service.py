"""Browser Pool Service for XHS Operations.

Manages browser instance lifecycle with pooling, health monitoring and
automatic cleanup.

Note: as in the TypeScript original, nothing in the shipped code paths turns
pooling on — every service builds a plain :class:`BrowserManager`. The pool is
kept because it is part of the public surface (``BrowserPoolService``,
``get_browser_pool``, ``cleanup_browser_pool``) and callers may opt in with
``BrowserManager(config, use_pool=True)``.

This is the one component that deliberately bypasses
:mod:`xhs_mcp.core.browser.session_manager`: a pool means several browsers,
which is the opposite of the one-profile-one-instance invariant that layer
exists to hold.

⚠️ Pooled browsers are **not** signed in. The login session lives in a single
persistent Chromium profile, and a profile directory can only be opened by one
browser process at a time, so a pool of browsers cannot share it. Pooled
instances therefore run in isolated, non-persistent contexts and are only
useful for work that needs no authentication.
"""

from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime

from cloakbrowser import launch_async

from ...shared.config import get_config
from ...shared.errors import BrowserLaunchError, XHSError
from ...shared.logger import logger
from ...shared.types import Config
from ...shared.utils import sleep
from .browser_types import BrowserPoolOptions, BrowserPoolStats, ManagedBrowser


def _now_ms() -> float:
    return time.time() * 1000


class BrowserPoolService:
    """A size-bounded pool of browsers with health checks and idle reaping."""

    def __init__(
        self, config: Config | None = None, options: BrowserPoolOptions | None = None
    ) -> None:
        self.config = config or get_config()
        self.pool: dict[str, ManagedBrowser] = {}
        self.options = options or BrowserPoolOptions()

        self._health_check_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._is_shutting_down = False
        self._monitoring_started = False
        self._warned_about_session = False

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    async def acquire_browser(self, timeout: int = 30000) -> ManagedBrowser:
        """Take an available browser, growing the pool up to ``max_instances``."""
        if self._is_shutting_down:
            raise XHSError("Browser pool is shutting down", "BrowserPoolError")

        if not self._warned_about_session:
            self._warned_about_session = True
            logger.warn(
                "Browser pool instances are NOT signed in: the login session lives "
                "in a single persistent Chromium profile, which only one browser "
                "process can open at a time. Use BrowserManager without a pool for "
                "anything that needs authentication."
            )

        self._ensure_monitoring()

        start_time = _now_ms()

        while _now_ms() - start_time < timeout:
            available = self._find_available_browser()
            if available is not None:
                available.is_available = False
                available.last_used = datetime.now()
                available.usage_count += 1
                logger.debug(f"Acquired browser {available.id} from pool")
                return available

            if len(self.pool) < self.options.max_instances:
                try:
                    new_browser = await self._create_browser_instance()
                    new_browser.is_available = False
                    new_browser.last_used = datetime.now()
                    new_browser.usage_count += 1
                    logger.info(f"Created new browser {new_browser.id} for pool")
                    return new_browser
                except Exception as error:
                    logger.error(f"Failed to create new browser instance: {error}")

            await sleep(100)

        raise XHSError(
            f"Failed to acquire browser within {timeout}ms timeout",
            "BrowserPoolTimeout",
            {
                "timeout": timeout,
                "poolSize": len(self.pool),
                "availableCount": self._get_available_count(),
            },
        )

    async def release_browser(self, browser: ManagedBrowser) -> None:
        """Return a browser to the pool, retiring it when stale or unhealthy."""
        managed = self.pool.get(browser.id)
        if managed is None:
            logger.warn(f"Attempted to release unknown browser {browser.id}")
            return

        # idle_timeout <= 0 means "don't keep instances around at all".
        if self.options.idle_timeout <= 0:
            logger.debug(
                f"Browser {browser.id} released with idleTimeout=0, closing immediately"
            )
            await self._remove_browser_from_pool(browser.id)
            await self._ensure_minimum_instances()
            return

        should_retire = self._should_retire_browser(managed)
        if should_retire:
            logger.info(f"Retiring browser {browser.id} due to {should_retire}")
            await self._remove_browser_from_pool(browser.id)
            await self._ensure_minimum_instances()
            return

        if not await self._check_browser_health(managed):
            logger.warn(f"Browser {browser.id} failed health check, removing from pool")
            await self._remove_browser_from_pool(browser.id)
            await self._ensure_minimum_instances()
            return

        managed.is_available = True
        managed.is_healthy = True
        logger.debug(f"Released browser {browser.id} back to pool")

    # ------------------------------------------------------------------
    # Stats and shutdown
    # ------------------------------------------------------------------

    def get_pool_stats(self) -> BrowserPoolStats:
        instances = list(self.pool.values())
        ages = [_now_ms() - b.created_at.timestamp() * 1000 for b in instances]

        return {
            "totalInstances": len(instances),
            "availableInstances": sum(
                1 for b in instances if b.is_available and b.is_healthy
            ),
            "busyInstances": sum(1 for b in instances if not b.is_available),
            "unhealthyInstances": sum(1 for b in instances if not b.is_healthy),
            "totalUsage": sum(b.usage_count for b in instances),
            "averageAge": (sum(ages) / len(ages)) if ages else 0,
            "oldestInstance": (
                min(instances, key=lambda b: b.created_at).created_at.isoformat()
                if instances
                else None
            ),
            "newestInstance": (
                max(instances, key=lambda b: b.created_at).created_at.isoformat()
                if instances
                else None
            ),
        }

    async def cleanup(self) -> None:
        self._is_shutting_down = True

        for task in (self._health_check_task, self._cleanup_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._health_check_task = None
        self._cleanup_task = None

        for managed in list(self.pool.values()):
            try:
                await managed.browser.close()
                logger.debug(f"Closed browser {managed.id}")
            except Exception as error:
                logger.warn(f"Error closing browser {managed.id}: {error}")

        self.pool.clear()
        logger.info("Browser pool cleanup completed")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _create_browser_instance(self) -> ManagedBrowser:
        try:
            browser = await launch_async(headless=self.config.browser.headless_default)
            context = await browser.new_context()

            managed = ManagedBrowser(
                browser=browser,
                context=context,
                id=self._generate_browser_id(),
                created_at=datetime.now(),
                last_used=datetime.now(),
            )

            self.pool[managed.id] = managed

            browser.on(
                "disconnected",
                lambda _: asyncio.ensure_future(  # noqa: RUF006 - fire-and-forget
                    self._handle_browser_disconnection(managed.id)
                ),
            )

            return managed
        except Exception as error:
            logger.error(f"Failed to create browser instance: {error}")
            raise BrowserLaunchError(
                f"Failed to create browser instance: {error}",
                {"poolSize": len(self.pool)},
                error,
            ) from error

    def _find_available_browser(self) -> ManagedBrowser | None:
        for browser in self.pool.values():
            if browser.is_available and browser.is_healthy:
                return browser
        return None

    def _should_retire_browser(self, browser: ManagedBrowser) -> str | None:
        age = _now_ms() - browser.created_at.timestamp() * 1000

        if age > self.options.max_age:
            return "max age exceeded"

        if browser.usage_count >= self.options.max_usage_count:
            return "max usage count exceeded"

        return None

    async def _check_browser_health(self, browser: ManagedBrowser) -> bool:
        try:
            if not browser.browser.is_connected():
                return False

            page = await browser.context.new_page()
            await page.close()
            return True
        except Exception as error:
            logger.debug(f"Browser {browser.id} health check failed: {error}")
            return False

    async def _remove_browser_from_pool(self, browser_id: str) -> None:
        browser = self.pool.get(browser_id)
        if browser is None:
            return

        try:
            await browser.browser.close()
        except Exception as error:
            logger.warn(f"Error closing browser {browser_id}: {error}")

        self.pool.pop(browser_id, None)
        logger.debug(f"Removed browser {browser_id} from pool")

    async def _handle_browser_disconnection(self, browser_id: str) -> None:
        browser = self.pool.get(browser_id)
        if browser is not None:
            browser.is_healthy = False
            browser.is_available = False

        await self._remove_browser_from_pool(browser_id)
        await self._ensure_minimum_instances()

    async def _ensure_minimum_instances(self) -> None:
        if self._is_shutting_down:
            return

        healthy_count = sum(1 for b in self.pool.values() if b.is_healthy)
        needed = self.options.min_instances - healthy_count

        if needed > 0:
            logger.info(
                f"Creating {needed} browser instances to maintain minimum pool size"
            )
            results = await asyncio.gather(
                *(self._create_browser_instance() for _ in range(needed)),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    logger.error(
                        f"Failed to create browser for minimum instances: {result}"
                    )

    def _get_available_count(self) -> int:
        return sum(1 for b in self.pool.values() if b.is_available and b.is_healthy)

    def _ensure_monitoring(self) -> None:
        """Start the background timers.

        Deferred until the first async call, because the constructor runs
        outside a running event loop.
        """
        if self._monitoring_started:
            return
        self._monitoring_started = True
        self._health_check_task = asyncio.ensure_future(self._health_monitor_loop())
        self._cleanup_task = asyncio.ensure_future(self._cleanup_monitor_loop())

    async def _health_monitor_loop(self) -> None:
        while not self._is_shutting_down:
            await sleep(self.options.health_check_interval)
            if self._is_shutting_down:
                return

            unhealthy: list[str] = []

            for browser_id, browser in list(self.pool.items()):
                if not browser.is_available:
                    continue  # Skip browsers currently in use.

                if not await self._check_browser_health(browser):
                    unhealthy.append(browser_id)
                    browser.is_healthy = False

            for browser_id in unhealthy:
                logger.warn(f"Removing unhealthy browser {browser_id} during health check")
                await self._remove_browser_from_pool(browser_id)

            if unhealthy:
                await self._ensure_minimum_instances()

    async def _cleanup_monitor_loop(self) -> None:
        while not self._is_shutting_down:
            await sleep(self.options.health_check_interval)
            if self._is_shutting_down:
                return

            now = _now_ms()
            to_remove: list[str] = []

            for browser_id, browser in list(self.pool.items()):
                idle_time = now - browser.last_used.timestamp() * 1000
                should_retire = self._should_retire_browser(browser)

                # A browser that is busy well past the stuck timeout usually means
                # an exception skipped its release_browser() call.
                is_stuck = (
                    not browser.is_available and idle_time > self.options.stuck_timeout
                )

                if idle_time > self.options.idle_timeout or should_retire or is_stuck:
                    healthy_count = sum(1 for b in self.pool.values() if b.is_healthy)

                    # Stuck browsers are force-removed regardless of the minimum.
                    if is_stuck or healthy_count > self.options.min_instances:
                        to_remove.append(browser_id)

            for browser_id in to_remove:
                browser = self.pool.get(browser_id)
                is_stuck = browser is not None and not browser.is_available
                reason = (
                    (self._should_retire_browser(browser) if browser else None)
                    or ("stuck browser timeout" if is_stuck else "idle timeout")
                )
                logger.info(f"Removing browser {browser_id} due to {reason}")

                if is_stuck and browser is not None:
                    try:
                        for page in browser.context.pages:
                            try:
                                if not page.is_closed():
                                    await page.close()
                            except Exception:
                                pass
                    except Exception:
                        pass

                await self._remove_browser_from_pool(browser_id)

            if to_remove:
                await self._ensure_minimum_instances()

    @staticmethod
    def _generate_browser_id() -> str:
        suffix = "".join(
            random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(9)
        )
        return f"browser_{int(_now_ms())}_{suffix}"


_global_browser_pool: BrowserPoolService | None = None


def get_browser_pool() -> BrowserPoolService:
    global _global_browser_pool
    if _global_browser_pool is None:
        _global_browser_pool = BrowserPoolService()
    return _global_browser_pool


async def cleanup_browser_pool() -> None:
    global _global_browser_pool
    if _global_browser_pool is not None:
        await _global_browser_pool.cleanup()
        _global_browser_pool = None
