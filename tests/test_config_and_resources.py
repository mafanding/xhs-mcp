"""Configuration defaults, environment overrides and MCP resource payloads."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from xhs_mcp.server.handlers.resource_handlers import ResourceHandlers
from xhs_mcp.shared import config as config_module
from xhs_mcp.shared.config import ConfigManager, config_to_json_dict, get_config


@pytest.fixture
def default_config():
    return ConfigManager._create_default_config()


def test_paths_default_to_home_xhs_mcp(default_config) -> None:
    assert default_config.paths.app_data_dir == str(Path.home() / ".xhs-mcp")
    assert default_config.paths.cookies_file == str(
        Path.home() / ".xhs-mcp" / "cookies.json"
    )


def test_browser_defaults(default_config) -> None:
    assert default_config.browser.default_timeout == 30000
    assert default_config.browser.login_timeout == 300
    assert default_config.browser.page_load_timeout == 30000
    assert default_config.browser.navigation_timeout == 30000
    assert default_config.browser.slowmo == 0
    assert default_config.browser.headless_default is True


def test_xhs_urls_match_the_original(default_config) -> None:
    xhs = default_config.xhs
    assert xhs.home_url == "https://www.xiaohongshu.com"
    assert xhs.explore_url == "https://www.xiaohongshu.com/explore"
    assert xhs.search_url == "https://www.xiaohongshu.com/search_result"
    assert xhs.creator_publish_url == (
        "https://creator.xiaohongshu.com/publish/publish?source=official"
    )
    assert xhs.creator_video_publish_url == (
        "https://creator.xiaohongshu.com/publish/publish"
        "?source=official&from=tab_switch&target=video"
    )
    assert xhs.login_ok_selector == ".main-container .user .link-wrapper .channel"
    assert xhs.max_retries == 3
    assert xhs.retry_delay == 2.0
    assert xhs.request_delay == 1.0


def test_server_defaults(default_config) -> None:
    assert default_config.server.name == "xhs-mcp"
    assert default_config.server.default_host == "127.0.0.1"
    assert default_config.server.default_port == 8000
    assert default_config.server.default_transport == "stdio"


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [("true", True), ("TRUE", True), ("false", False), ("anything", False)],
)
def test_headless_env_override(
    monkeypatch: pytest.MonkeyPatch, env_value: str, expected: bool
) -> None:
    monkeypatch.setenv("XHS_HEADLESS", env_value)
    assert ConfigManager._create_default_config().browser.headless_default is expected


def test_numeric_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_BROWSER_TIMEOUT", "12345")
    monkeypatch.setenv("XHS_LOGIN_TIMEOUT", "60")
    monkeypatch.setenv("XHS_PORT", "9999")

    config = ConfigManager._create_default_config()
    assert config.browser.default_timeout == 12345
    assert config.browser.login_timeout == 60
    assert config.server.default_port == 9999


def test_invalid_numeric_env_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XHS_BROWSER_TIMEOUT", "not-a-number")
    assert ConfigManager._create_default_config().browser.default_timeout == 30000


def test_log_file_path_only_set_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ConfigManager._create_default_config().logging.file_path is None

    monkeypatch.setenv("XHS_LOG_FILE", "true")
    config = ConfigManager._create_default_config()
    assert config.logging.file_enabled is True
    assert config.logging.file_path.endswith("xhs-mcp.log")


def test_config_to_json_dict_uses_camel_case(default_config) -> None:
    payload = config_to_json_dict(default_config)

    assert set(payload) == {"browser", "server", "logging", "paths", "xhs"}
    assert "defaultTimeout" in payload["browser"]
    assert "headlessDefault" in payload["browser"]
    assert "cookiesFile" in payload["paths"]
    assert "creatorVideoPublishUrl" in payload["xhs"]
    assert "loginOkSelector" in payload["xhs"]


@pytest.fixture
def isolated_cookies(tmp_path: Path) -> Iterator[None]:
    original = get_config()
    config_module.set_config(
        replace(
            original,
            paths=replace(
                original.paths,
                app_data_dir=str(tmp_path),
                cookies_file=str(tmp_path / "cookies.json"),
            ),
        )
    )
    yield
    config_module.set_config(original)


async def test_cookies_resource(isolated_cookies: None) -> None:
    payload = json.loads(await ResourceHandlers().get_cookies_resource())

    assert payload["fileExists"] is False
    assert payload["cookieCount"] == 0


async def test_config_resource_includes_framework_and_version() -> None:
    payload = json.loads(await ResourceHandlers().get_config_resource())

    assert payload["framework"] == "MCP Python"
    assert payload["version"] == get_config().server.version
    assert payload["xhs"]["homeUrl"] == "https://www.xiaohongshu.com"


async def test_unknown_resource_returns_error_payload() -> None:
    result = await ResourceHandlers().handle_resource_request("xhs://nope")

    content = result["contents"][0]
    assert content["uri"] == "xhs://nope"
    assert content["mimeType"] == "application/json"
    assert json.loads(content["text"])["error"] == "Unknown resource: xhs://nope"


async def test_known_resource_request_shape(isolated_cookies: None) -> None:
    result = await ResourceHandlers().handle_resource_request("xhs://cookies")

    assert len(result["contents"]) == 1
    assert result["contents"][0]["uri"] == "xhs://cookies"
    assert result["contents"][0]["mimeType"] == "application/json"
