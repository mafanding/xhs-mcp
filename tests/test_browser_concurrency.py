"""Concurrency behaviour of :class:`BrowserManager`.

One browser process holding one profile serves concurrent work through
multiple tabs. Two things have to hold for that to work:

1. Concurrent callers must not each try to launch a browser — a profile
   directory can only be opened once, so the losers would die on Chromium's
   ProcessSingleton lock.
2. Leak detection must not close tabs that other operations are still using.

These use a fake context so no browser is launched.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xhs_mcp.core.browser.browser_manager import BrowserManager


class _FakePage:
    def __init__(self) -> None:
        self.closed = False
        self._handlers: dict[str, Any] = {}
        self.context = _FakeContext.current

    def once(self, event: str, handler: Any) -> None:
        self._handlers[event] = handler

    def set_default_timeout(self, _timeout: int) -> None:
        pass

    def set_default_navigation_timeout(self, _timeout: int) -> None:
        pass

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True
        handler = self._handlers.get("close")
        if handler:
            handler(self)


class _FakeContext:
    current: _FakeContext | None = None

    def __init__(self) -> None:
        self.pages: list[_FakePage] = []
        _FakeContext.current = self

    async def new_page(self) -> _FakePage:
        page = _FakePage()
        return page

    async def cookies(self, *_args: Any) -> list[dict[str, Any]]:
        return [{"name": "web_session"}]

    async def add_cookies(self, _cookies: Any) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> BrowserManager:
    """A manager whose launch is slow enough to expose a race."""
    instance = BrowserManager()
    launches = {"count": 0}

    async def fake_launch(*_args: Any, **_kwargs: Any) -> _FakeContext:
        launches["count"] += 1
        await asyncio.sleep(0.05)  # widen the window for a racing caller
        return _FakeContext()

    monkeypatch.setattr(instance, "_launch_context", fake_launch)
    instance.launches = launches  # type: ignore[attr-defined]
    return instance


async def test_concurrent_cold_start_launches_exactly_one_browser(
    manager: BrowserManager,
) -> None:
    """Without this, every caller but one dies on the profile lock."""
    pages = await asyncio.gather(*(manager.create_page(True) for _ in range(6)))

    assert manager.launches["count"] == 1  # type: ignore[attr-defined]
    assert len(pages) == 6
    assert len({id(page) for page in pages}) == 6


async def test_sequential_calls_reuse_the_same_context(manager: BrowserManager) -> None:
    await manager.create_page(True)
    await manager.create_page(True)

    assert manager.launches["count"] == 1  # type: ignore[attr-defined]


async def test_many_live_tabs_are_not_closed_by_leak_detection(
    manager: BrowserManager,
) -> None:
    """Exceeding the threshold must not kill work that is still in flight."""
    pages = [await manager.create_page(True) for _ in range(manager._max_tracked_pages + 5)]

    assert all(not page.is_closed() for page in pages)
    assert manager.get_tracked_page_count() == len(pages)


async def test_stale_pages_are_reclaimed(manager: BrowserManager) -> None:
    """A page left open past the stale age is a genuine leak."""
    leaked = await manager.create_page(True)

    # Backdate it beyond the stale threshold.
    manager._tracked_pages[leaked] -= manager._stale_page_age + 1_000

    fresh = [await manager.create_page(True) for _ in range(manager._max_tracked_pages)]

    assert leaked.is_closed()
    assert all(not page.is_closed() for page in fresh)


async def test_closing_a_page_stops_tracking_it(manager: BrowserManager) -> None:
    page = await manager.create_page(True)
    assert manager.get_tracked_page_count() == 1

    await page.close()

    assert manager.get_tracked_page_count() == 0


async def test_cleanup_closes_every_tracked_page(manager: BrowserManager) -> None:
    pages = [await manager.create_page(True) for _ in range(3)]

    await manager.cleanup()

    assert all(page.is_closed() for page in pages)
    assert manager.get_tracked_page_count() == 0
