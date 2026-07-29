"""Legacy cookie-file import.

The session now lives in a persistent Chromium profile. The cookie file is
read-only legacy: it exists solely so an installation that logged in under the
old scheme can migrate without logging in again.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from xhs_mcp.core.browser.browser_manager import to_playwright_cookies
from xhs_mcp.shared import config as config_module
from xhs_mcp.shared import cookies as cookies_module
from xhs_mcp.shared.cookies import (
    delete_cookies_file,
    get_cookies_file_path,
    has_legacy_cookies,
    load_cookies,
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


def _write(path: Path, cookies: list[dict]) -> None:
    path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------


def test_load_returns_none_when_absent() -> None:
    assert load_cookies() is None
    assert has_legacy_cookies() is False


def test_load_reads_the_typescript_format(temp_cookie_file: Path) -> None:
    """The file written by the TS version must still import cleanly."""
    _write(temp_cookie_file, _SAMPLE)

    assert has_legacy_cookies() is True
    assert load_cookies() == _SAMPLE


def test_load_returns_none_on_invalid_json(temp_cookie_file: Path) -> None:
    temp_cookie_file.write_text("{not json")
    assert load_cookies() is None


def test_get_cookies_file_path_follows_config(temp_cookie_file: Path) -> None:
    assert get_cookies_file_path() == str(temp_cookie_file)


def test_cookies_module_no_longer_writes() -> None:
    """Nothing may write the legacy file - the profile is the session store."""
    assert not hasattr(cookies_module, "save_cookies")


# ----------------------------------------------------------------------
# Deletion
# ----------------------------------------------------------------------


def test_delete_cookies_file(temp_cookie_file: Path) -> None:
    _write(temp_cookie_file, _SAMPLE)

    assert delete_cookies_file() is True
    assert not temp_cookie_file.exists()
    # Deleting an absent file still reports success.
    assert delete_cookies_file() is True


# ----------------------------------------------------------------------
# Conversion for Playwright
# ----------------------------------------------------------------------


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
