"""The entry layer holds services, never browser objects.

Entry points (CLI, MCP stdio, MCP HTTP) issue requests. Reaching a browser is
the instance manager's job, so the boundary is worth asserting: a regression
here is invisible until two entry points fight over a profile.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from xhs_mcp.cli import cli as cli_module
from xhs_mcp.core.browser import session_manager as sm
from xhs_mcp.core.browser.session_manager import BrowserSessionManager
from xhs_mcp.server.handlers.tool_handlers import ToolHandlers

_ENTRY_MODULES = [
    "src/xhs_mcp/cli/cli.py",
    "src/xhs_mcp/server/handlers/tool_handlers.py",
    "src/xhs_mcp/server/handlers/resource_handlers.py",
    "src/xhs_mcp/server/mcp_server.py",
    "src/xhs_mcp/server/http_server.py",
]


@pytest.mark.parametrize("module_path", _ENTRY_MODULES)
def test_entry_layer_does_not_import_the_browser_layer(module_path: str) -> None:
    source = Path(module_path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)

    offenders = [
        name
        for name in imported
        if "browser_manager" in name or "browser_pool" in name
    ]
    assert not offenders, f"{module_path} imports the browser layer: {offenders}"


@pytest.mark.parametrize("module_path", _ENTRY_MODULES)
def test_entry_layer_never_constructs_a_browser_manager(module_path: str) -> None:
    source = Path(module_path).read_text(encoding="utf-8")

    assert "BrowserManager(" not in source, module_path


def test_tool_handlers_holds_only_services() -> None:
    handlers = ToolHandlers()

    browserish = [
        name
        for name, value in vars(handlers).items()
        if type(value).__name__ in ("BrowserManager", "BrowserPoolService")
    ]
    assert not browserish, f"entry layer holds browser objects: {browserish}"

    assert hasattr(handlers, "auth_service")
    assert hasattr(handlers, "feed_service")
    assert hasattr(handlers, "publish_service")
    assert hasattr(handlers, "note_service")


def test_cli_state_holds_no_browser_objects() -> None:
    state = cli_module.CLIState()

    assert not hasattr(state, "browser_managers")
    assert not hasattr(state, "track")
    assert vars(state) == {"compact": False}


def test_cli_teardown_goes_through_the_instance_manager() -> None:
    source = inspect.getsource(cli_module.CLIState.cleanup)

    assert "get_session_manager" in source
    assert "browser_manager" not in source


def test_tool_handlers_shutdown_goes_through_the_instance_manager() -> None:
    source = inspect.getsource(ToolHandlers.shutdown)

    assert "get_session_manager" in source


async def test_shutdown_all_releases_every_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = BrowserSessionManager()
    closed: list[str] = []

    class _Context:
        def __init__(self, name: str) -> None:
            self.name = name
            self.pages: list[str] = []

        async def close(self) -> None:
            closed.append(self.name)

    async def launch(user_data_dir: str, headless: bool, args=None, humanize: bool = False) -> _Context:
        return _Context(user_data_dir)

    monkeypatch.setattr(sm, "launch_persistent_context_async", launch)
    monkeypatch.setattr(sm, "ensure_user_data_dir", lambda _d: None)
    monkeypatch.setattr(sm, "read_devtools_endpoint", lambda _d: None)

    await manager.acquire("/a", True)
    await manager.acquire("/a", True)  # two references
    await manager.acquire("/b", True)

    await manager.shutdown_all()

    assert sorted(closed) == ["/a", "/b"], "refcounts must not outlive the process"
    assert manager._sessions == {}


async def test_shutdown_all_only_disconnects_attached_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exiting must not kill a browser another process owns."""
    manager = BrowserSessionManager()

    class _Context:
        pages: list[str] = []
        closed = False

        async def close(self) -> None:
            type(self).closed = True

    context = _Context()

    class _Browser:
        def __init__(self) -> None:
            self.closed = False
            self.contexts = [context]

        async def close(self) -> None:
            self.closed = True

    browser = _Browser()

    class _PW:
        def __init__(self) -> None:
            self.stopped = False
            self.chromium = self

        async def connect_over_cdp(self, _e: str) -> _Browser:
            return browser

        async def stop(self) -> None:
            self.stopped = True

    playwright = _PW()

    monkeypatch.setattr(sm, "read_devtools_endpoint", lambda _d: "http://127.0.0.1:1")

    async def live(_e: str) -> bool:
        return True

    monkeypatch.setattr(sm, "_endpoint_is_live", live)

    class _Starter:
        async def start(self) -> _PW:
            return playwright

    monkeypatch.setattr(sm, "async_playwright", lambda: _Starter())

    await manager.acquire("/shared", True)
    await manager.shutdown_all()

    assert browser.closed is True, "our CDP connection is dropped"
    assert playwright.stopped is True
    assert _Context.closed is False, "the owner's browser keeps running"


async def test_shutdown_all_is_safe_when_nothing_was_acquired() -> None:
    await BrowserSessionManager().shutdown_all()
