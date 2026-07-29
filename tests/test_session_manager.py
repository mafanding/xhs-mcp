"""The browser instance management layer.

Its whole job is one invariant — **one profile directory, one browser
instance** — held both within a process and across processes, so entry points
never have to care how a browser is obtained.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from xhs_mcp.core.browser import session_manager as sm
from xhs_mcp.core.browser.session_manager import (
    BrowserSessionManager,
    read_devtools_endpoint,
)
from xhs_mcp.shared.errors import BrowserLaunchError


class _FakeContext:
    def __init__(self) -> None:
        self.pages: list[str] = ["initial-page"]
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, contexts: list[Any]) -> None:
        self.contexts = contexts
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser
        self.stopped = False
        self.chromium = self

    async def connect_over_cdp(self, _endpoint: str) -> _FakeBrowser:
        return self._browser

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture
def manager() -> BrowserSessionManager:
    return BrowserSessionManager()


@pytest.fixture
def no_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    """No live browser is discoverable."""
    monkeypatch.setattr(sm, "read_devtools_endpoint", lambda _dir: None)


@pytest.fixture
def fake_launch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"count": 0, "args": None}

    async def launch(user_data_dir: str, headless: bool, args: Any = None, humanize: bool = False) -> _FakeContext:
        state["count"] += 1
        state["args"] = args
        state["headless"] = headless
        return _FakeContext()

    monkeypatch.setattr(sm, "launch_persistent_context_async", launch)
    monkeypatch.setattr(sm, "ensure_user_data_dir", lambda _dir: None)
    return state


# ----------------------------------------------------------------------
# Endpoint discovery
# ----------------------------------------------------------------------


def test_endpoint_is_none_without_the_port_file(tmp_path: Path) -> None:
    assert read_devtools_endpoint(str(tmp_path)) is None


def test_endpoint_is_parsed_from_the_port_file(tmp_path: Path) -> None:
    (tmp_path / "DevToolsActivePort").write_text("54321\n/devtools/browser/abc")

    assert read_devtools_endpoint(str(tmp_path)) == "http://127.0.0.1:54321"


@pytest.mark.parametrize("content", ["", "not-a-port", "0", "-1"])
def test_malformed_port_file_is_ignored(tmp_path: Path, content: str) -> None:
    (tmp_path / "DevToolsActivePort").write_text(content)

    assert read_devtools_endpoint(str(tmp_path)) is None


# ----------------------------------------------------------------------
# One instance per profile, in-process
# ----------------------------------------------------------------------


async def test_second_acquire_reuses_the_same_instance(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    first = await manager.acquire("/p", True)
    second = await manager.acquire("/p", True)

    assert first is second
    assert fake_launch["count"] == 1, "a profile must never get a second browser"
    assert second.ref_count == 2


async def test_different_profiles_get_different_instances(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    a = await manager.acquire("/a", True)
    b = await manager.acquire("/b", True)

    assert a is not b
    assert fake_launch["count"] == 2


async def test_instance_survives_until_the_last_reference_is_released(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    session = await manager.acquire("/p", True)
    await manager.acquire("/p", True)

    await manager.release("/p")
    assert session.context.closed is False, "still in use by the other holder"

    await manager.release("/p")
    assert session.context.closed is True


async def test_releasing_an_unknown_profile_is_a_no_op(
    manager: BrowserSessionManager,
) -> None:
    await manager.release("/never-acquired")


async def test_a_released_profile_can_be_acquired_again(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    await manager.acquire("/p", True)
    await manager.release("/p")
    await manager.acquire("/p", True)

    assert fake_launch["count"] == 2


async def test_launch_is_discoverable_by_other_processes(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    """Without the debug port no other process could find this instance."""
    await manager.acquire("/p", True)

    assert "--remote-debugging-port=0" in fake_launch["args"]


async def test_extra_browser_args_are_passed_through(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    await manager.acquire("/p", True, ["--no-sandbox"])

    assert "--no-sandbox" in fake_launch["args"]


async def test_owner_hands_out_the_preopened_page(
    manager: BrowserSessionManager, no_attach: None, fake_launch: dict[str, Any]
) -> None:
    session = await manager.acquire("/p", True)

    assert session.owns_browser is True
    assert session.unclaimed_pages == ["initial-page"]


# ----------------------------------------------------------------------
# Attaching across processes
# ----------------------------------------------------------------------


@pytest.fixture
def fake_attach(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    context = _FakeContext()
    browser = _FakeBrowser([context])
    playwright = _FakePlaywright(browser)

    monkeypatch.setattr(sm, "read_devtools_endpoint", lambda _d: "http://127.0.0.1:1234")

    async def live(_endpoint: str) -> bool:
        return True

    monkeypatch.setattr(sm, "_endpoint_is_live", live)

    class _Starter:
        async def start(self) -> _FakePlaywright:
            return playwright

    monkeypatch.setattr(sm, "async_playwright", lambda: _Starter())
    return {"context": context, "browser": browser, "playwright": playwright}


async def test_attaches_instead_of_launching(
    manager: BrowserSessionManager, fake_attach: dict[str, Any], fake_launch: dict[str, Any]
) -> None:
    session = await manager.acquire("/p", True)

    assert fake_launch["count"] == 0, "must not start a second browser"
    assert session.owns_browser is False
    assert session.context is fake_attach["context"]


async def test_attached_session_never_claims_existing_pages(
    manager: BrowserSessionManager, fake_attach: dict[str, Any]
) -> None:
    """Those tabs belong to whoever opened them, in another process."""
    session = await manager.acquire("/p", True)

    assert session.unclaimed_pages == []


async def test_releasing_an_attached_session_only_disconnects(
    manager: BrowserSessionManager, fake_attach: dict[str, Any]
) -> None:
    """A short CLI command must never kill a running server's browser."""
    await manager.acquire("/p", True)

    await manager.release("/p")

    assert fake_attach["browser"].closed is True, "the CDP connection is dropped"
    assert fake_attach["playwright"].stopped is True
    assert fake_attach["context"].closed is False, "the browser itself keeps running"


async def test_stale_port_file_falls_back_to_launching(
    manager: BrowserSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    fake_launch: dict[str, Any],
) -> None:
    monkeypatch.setattr(sm, "read_devtools_endpoint", lambda _d: "http://127.0.0.1:1")

    async def dead(_endpoint: str) -> bool:
        return False

    monkeypatch.setattr(sm, "_endpoint_is_live", dead)

    session = await manager.acquire("/p", True)

    assert fake_launch["count"] == 1
    assert session.owns_browser is True


# ----------------------------------------------------------------------
# Launch races and failures
# ----------------------------------------------------------------------


async def test_losing_the_launch_race_attaches_to_the_winner(
    manager: BrowserSessionManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two processes starting at once: the loser must attach, not fail."""
    context = _FakeContext()
    browser = _FakeBrowser([context])
    playwright = _FakePlaywright(browser)
    state = {"endpoint_ready": False}

    async def launch(*_a: Any, **_k: Any) -> Any:
        state["endpoint_ready"] = True  # the winner's browser is now up
        raise RuntimeError("Failed to create a ProcessSingleton for your profile")

    monkeypatch.setattr(sm, "launch_persistent_context_async", launch)
    monkeypatch.setattr(sm, "ensure_user_data_dir", lambda _d: None)
    monkeypatch.setattr(
        sm,
        "read_devtools_endpoint",
        lambda _d: "http://127.0.0.1:1234" if state["endpoint_ready"] else None,
    )

    async def live(_e: str) -> bool:
        return True

    monkeypatch.setattr(sm, "_endpoint_is_live", live)

    class _Starter:
        async def start(self) -> _FakePlaywright:
            return playwright

    monkeypatch.setattr(sm, "async_playwright", lambda: _Starter())
    monkeypatch.setattr(sm, "_LAUNCH_RACE_DELAY", 0)

    session = await manager.acquire("/p", True)

    assert session.owns_browser is False


async def test_a_non_lock_failure_is_reported_immediately(
    manager: BrowserSessionManager, monkeypatch: pytest.MonkeyPatch, no_attach: None
) -> None:
    async def launch(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("binary is missing")

    monkeypatch.setattr(sm, "launch_persistent_context_async", launch)
    monkeypatch.setattr(sm, "ensure_user_data_dir", lambda _d: None)

    with pytest.raises(BrowserLaunchError, match="binary is missing"):
        await manager.acquire("/p", True)


async def test_unrecoverable_lock_error_suggests_a_separate_profile(
    manager: BrowserSessionManager, monkeypatch: pytest.MonkeyPatch, no_attach: None
) -> None:
    """Attaching is never optional, so the only remaining advice is a new profile."""

    async def launch(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("Failed to create a ProcessSingleton for your profile")

    monkeypatch.setattr(sm, "launch_persistent_context_async", launch)
    monkeypatch.setattr(sm, "ensure_user_data_dir", lambda _d: None)
    monkeypatch.setattr(sm, "_LAUNCH_RACE_DELAY", 0)

    with pytest.raises(BrowserLaunchError) as excinfo:
        await manager.acquire("/p", True)

    assert "XHS_USER_DATA_DIR" in str(excinfo.value)


async def test_sharing_cannot_be_disabled_by_configuration(
    manager: BrowserSessionManager,
    monkeypatch: pytest.MonkeyPatch,
    fake_attach: dict[str, Any],
    fake_launch: dict[str, Any],
) -> None:
    """The invariant is not a user-tunable setting."""
    monkeypatch.setenv("XHS_SHARE_BROWSER", "false")

    session = await manager.acquire("/p", True)

    assert session.owns_browser is False, "still attaches; the env var is inert"
    assert fake_launch["count"] == 0
