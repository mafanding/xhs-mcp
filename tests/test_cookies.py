"""Cookie persistence and Playwright conversion.

The on-disk format must stay interchangeable with the TypeScript version's
``~/.xhs-mcp/cookies.json``, and cookies written by Puppeteer carry extra keys
that Playwright rejects, so conversion has to filter them out.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from xhs_mcp.core.browser.browser_manager import to_playwright_cookies
from xhs_mcp.shared import config as config_module
from xhs_mcp.shared.cookies import (
    delete_cookies_file,
    get_cookies_file_path,
    get_cookies_info,
    load_cookies,
    save_cookies,
)

_SAMPLE = [
    {
        "name": "web_session",
        "value": "abc123",
        "domain": ".xiaohongshu.com",
        "path": "/",
        "expires": 1893456000,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }
]


@pytest.fixture(autouse=True)
def temp_cookie_file(tmp_path: Path) -> Iterator[Path]:
    """Point the cookie path at a temp file so tests never touch ``~/.xhs-mcp``."""
    original = config_module.get_config()
    path = tmp_path / "cookies.json"
    config_module.set_config(
        replace(
            original,
            paths=replace(
                original.paths, app_data_dir=str(tmp_path), cookies_file=str(path)
            ),
        )
    )
    yield path
    config_module.set_config(original)


def test_load_returns_none_when_absent() -> None:
    assert load_cookies() is None


def test_save_and_load_round_trip(temp_cookie_file: Path) -> None:
    save_cookies(_SAMPLE)
    assert load_cookies() == _SAMPLE
    # Written as pretty-printed JSON, like the original.
    assert temp_cookie_file.read_text().startswith("[\n")


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    original = config_module.get_config()
    nested = tmp_path / "deep" / "nested" / "cookies.json"
    config_module.set_config(
        replace(original, paths=replace(original.paths, cookies_file=str(nested)))
    )
    try:
        save_cookies(_SAMPLE)
        assert nested.exists()
    finally:
        config_module.set_config(original)


def test_saving_empty_list_is_a_no_op(temp_cookie_file: Path) -> None:
    save_cookies(_SAMPLE)
    save_cookies([])
    # A good cookie file is never clobbered by an empty save.
    assert load_cookies() == _SAMPLE


def test_load_returns_none_on_invalid_json(temp_cookie_file: Path) -> None:
    temp_cookie_file.write_text("{not json")
    assert load_cookies() is None


def test_delete_cookies_file(temp_cookie_file: Path) -> None:
    save_cookies(_SAMPLE)
    assert delete_cookies_file() is True
    assert not temp_cookie_file.exists()
    # Deleting an absent file still reports success.
    assert delete_cookies_file() is True


def test_get_cookies_info(temp_cookie_file: Path) -> None:
    info = get_cookies_info()
    assert info["fileExists"] is False
    assert info["cookieCount"] == 0
    # JSON.stringify dropped the undefined value, so the key must be absent
    # rather than null - clients may test with `"lastModified" in info`.
    assert "lastModified" not in info
    assert info["filePath"] == str(temp_cookie_file)

    save_cookies(_SAMPLE)
    info = get_cookies_info()
    assert info["fileExists"] is True
    assert info["cookieCount"] == 1
    # Milliseconds since the epoch, matching JavaScript's Date#getTime().
    assert info["lastModified"] > 1_000_000_000_000


def test_get_cookies_file_path_follows_config(temp_cookie_file: Path) -> None:
    assert get_cookies_file_path() == str(temp_cookie_file)


def test_to_playwright_cookies_drops_puppeteer_only_keys() -> None:
    puppeteer_cookie = {
        **_SAMPLE[0],
        "size": 42,
        "session": False,
        "sourceScheme": "Secure",
        "partitionKey": None,
        "priority": "Medium",
    }

    converted = to_playwright_cookies([puppeteer_cookie])

    assert converted == _SAMPLE
    assert set(converted[0]) <= {
        "name",
        "value",
        "domain",
        "path",
        "expires",
        "httpOnly",
        "secure",
        "sameSite",
    }


@pytest.mark.parametrize("same_site", ["unspecified", "no_restriction", "", None, "bogus"])
def test_to_playwright_cookies_drops_invalid_same_site(same_site: object) -> None:
    converted = to_playwright_cookies([{**_SAMPLE[0], "sameSite": same_site}])
    assert "sameSite" not in converted[0]


@pytest.mark.parametrize("same_site", ["Strict", "Lax", "None"])
def test_to_playwright_cookies_keeps_valid_same_site(same_site: str) -> None:
    converted = to_playwright_cookies([{**_SAMPLE[0], "sameSite": same_site}])
    assert converted[0]["sameSite"] == same_site


def test_to_playwright_cookies_preserves_session_expiry() -> None:
    converted = to_playwright_cookies([{**_SAMPLE[0], "expires": -1}])
    assert converted[0]["expires"] == -1


def test_to_playwright_cookies_skips_incomplete_cookies() -> None:
    incomplete = [
        {"value": "v", "domain": ".x.com", "path": "/"},  # no name
        {"name": "n", "domain": ".x.com", "path": "/"},  # no value
        {"name": "n", "value": "v", "path": "/"},  # no domain
        {"name": "n", "value": "v", "domain": ".x.com"},  # no path
    ]
    assert to_playwright_cookies(incomplete) == []


def test_cookie_file_stays_json_array_for_cross_version_compatibility(
    temp_cookie_file: Path,
) -> None:
    save_cookies(_SAMPLE)
    parsed = json.loads(temp_cookie_file.read_text())
    assert isinstance(parsed, list)
    assert parsed[0]["name"] == "web_session"
