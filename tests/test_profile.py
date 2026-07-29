"""Persistent browser profile mode (``XHS_USER_DATA_DIR``)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from xhs_mcp.shared import config as config_module
from xhs_mcp.shared.config import ConfigManager, config_to_json_dict
from xhs_mcp.shared.profile import (
    MARKER_FILENAME,
    clear_user_data_dir,
    count_profile_cookies,
    ensure_user_data_dir,
    get_profile_info,
    get_user_data_dir,
    is_owned_profile,
)


@pytest.fixture
def profile_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the config at a temp profile directory."""
    original = config_module.get_config()
    directory = tmp_path / "profile"
    config_module.set_config(
        replace(
            original,
            paths=replace(
                original.paths,
                cookies_file=str(tmp_path / "cookies.json"),
                user_data_dir=str(directory),
            ),
        )
    )
    yield directory
    config_module.set_config(original)


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------


def test_profile_defaults_to_app_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session always lives in a profile; there is no cookie-file mode."""
    monkeypatch.delenv("XHS_USER_DATA_DIR", raising=False)
    config = ConfigManager._create_default_config()
    assert config.paths.user_data_dir == str(Path.home() / ".xhs-mcp" / "profile")


def test_env_var_overrides_profile_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "/tmp/xhs-profile")
    assert (
        ConfigManager._create_default_config().paths.user_data_dir == "/tmp/xhs-profile"
    )


def test_env_var_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "~/xhs-profile")
    resolved = ConfigManager._create_default_config().paths.user_data_dir
    assert resolved == str(Path.home() / "xhs-profile")


def test_blank_env_var_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "   ")
    config = ConfigManager._create_default_config()
    assert config.paths.user_data_dir == str(Path.home() / ".xhs-mcp" / "profile")


def test_config_resource_reports_the_profile_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "/tmp/xhs-profile")
    payload = config_to_json_dict(ConfigManager._create_default_config())
    assert payload["paths"]["userDataDir"] == "/tmp/xhs-profile"
    # The cookie file is legacy and no longer part of the advertised config.
    assert "cookiesFile" not in payload["paths"]


def test_get_user_data_dir_follows_config(profile_dir: Path) -> None:
    assert get_user_data_dir() == str(profile_dir)


# ----------------------------------------------------------------------
# Directory ownership
# ----------------------------------------------------------------------


def test_ensure_creates_directory_and_marker(profile_dir: Path) -> None:
    ensure_user_data_dir(str(profile_dir))

    assert profile_dir.is_dir()
    assert (profile_dir / MARKER_FILENAME).exists()
    assert is_owned_profile(str(profile_dir))


def test_ensure_is_idempotent(profile_dir: Path) -> None:
    ensure_user_data_dir(str(profile_dir))
    original = (profile_dir / MARKER_FILENAME).read_text()

    ensure_user_data_dir(str(profile_dir))

    assert (profile_dir / MARKER_FILENAME).read_text() == original


def test_directory_without_marker_is_not_owned(tmp_path: Path) -> None:
    assert is_owned_profile(str(tmp_path)) is False


# ----------------------------------------------------------------------
# Logout cleanup
# ----------------------------------------------------------------------


def test_clear_removes_an_owned_profile(profile_dir: Path) -> None:
    ensure_user_data_dir(str(profile_dir))
    (profile_dir / "Default").mkdir()
    (profile_dir / "Default" / "Cookies").write_bytes(b"sqlite")

    cleared, error = clear_user_data_dir()

    assert cleared is True
    assert error is None
    assert not profile_dir.exists()


def test_clear_refuses_a_directory_it_does_not_own(profile_dir: Path) -> None:
    """Guards against XHS_USER_DATA_DIR pointing at a real Chrome profile."""
    profile_dir.mkdir(parents=True)
    (profile_dir / "History").write_text("irreplaceable user data")

    cleared, error = clear_user_data_dir()

    assert cleared is False
    assert error is not None
    assert MARKER_FILENAME in error
    assert (profile_dir / "History").exists(), "user data must not be destroyed"


def test_clear_is_a_no_op_when_directory_absent(profile_dir: Path) -> None:
    assert clear_user_data_dir() == (True, None)


# ----------------------------------------------------------------------
# Session reporting
# ----------------------------------------------------------------------


def test_profile_info_when_profile_absent(profile_dir: Path) -> None:
    info = get_profile_info()

    assert info["profileDir"] == str(profile_dir)
    assert info["profileExists"] is False
    assert info["cookieCount"] == 0
    assert "lastModified" not in info


def test_profile_info_counts_cookies_from_the_profile_database(
    profile_dir: Path,
) -> None:
    import sqlite3

    db = profile_dir / "Default" / "Cookies"
    db.parent.mkdir(parents=True)
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE cookies (name TEXT)")
    connection.executemany(
        "INSERT INTO cookies VALUES (?)", [("web_session",), ("a1",), ("webId",)]
    )
    connection.commit()
    connection.close()

    info = get_profile_info()

    assert info["profileExists"] is True
    assert info["cookieCount"] == 3
    assert info["lastModified"] > 1_000_000_000_000


def test_cookie_count_is_none_without_a_database(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True)
    assert count_profile_cookies(str(profile_dir)) is None


def test_cookie_count_tolerates_a_corrupt_database(profile_dir: Path) -> None:
    db = profile_dir / "Default" / "Cookies"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not a sqlite file")

    assert count_profile_cookies(str(profile_dir)) is None


# ----------------------------------------------------------------------
# Logout integration
# ----------------------------------------------------------------------


async def test_logout_deletes_the_profile(profile_dir: Path) -> None:
    from xhs_mcp.core.auth.auth_service import AuthService

    ensure_user_data_dir(str(profile_dir))
    result = await AuthService(config_module.get_config()).logout()

    assert result["success"] is True
    assert result["profileCleared"] is True
    assert result["status"] == "logged_out"
    assert result["action"] == "logged_out"
    assert "browser profile deleted" in result["message"]
    assert not profile_dir.exists()


async def test_logout_fails_loudly_when_the_profile_cannot_be_removed(
    profile_dir: Path,
) -> None:
    """Reporting success while still signed in would be worse than failing."""
    from xhs_mcp.core.auth.auth_service import AuthService

    profile_dir.mkdir(parents=True)  # no marker

    result = await AuthService(config_module.get_config()).logout()

    assert result["success"] is False
    assert result["profileCleared"] is False
    assert "Refused to delete browser profile" in result["message"]
    assert profile_dir.exists()


async def test_logout_also_removes_a_stale_legacy_cookie_file(
    profile_dir: Path, tmp_path: Path
) -> None:
    from xhs_mcp.core.auth.auth_service import AuthService

    legacy = Path(config_module.get_config().paths.cookies_file)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("[]")
    ensure_user_data_dir(str(profile_dir))

    await AuthService(config_module.get_config()).logout()

    assert not legacy.exists()
