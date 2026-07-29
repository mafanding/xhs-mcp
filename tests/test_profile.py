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
    ensure_user_data_dir,
    get_user_data_dir,
    is_owned_profile,
    is_profile_mode,
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


def test_profile_mode_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XHS_USER_DATA_DIR", raising=False)
    assert ConfigManager._create_default_config().paths.user_data_dir is None


def test_env_var_enables_profile_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "/tmp/xhs-profile")
    assert (
        ConfigManager._create_default_config().paths.user_data_dir == "/tmp/xhs-profile"
    )


def test_env_var_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "~/xhs-profile")
    resolved = ConfigManager._create_default_config().paths.user_data_dir
    assert resolved == str(Path.home() / "xhs-profile")


def test_blank_env_var_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "   ")
    assert ConfigManager._create_default_config().paths.user_data_dir is None


def test_config_resource_omits_user_data_dir_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default payload must stay identical to the TypeScript server's."""
    monkeypatch.delenv("XHS_USER_DATA_DIR", raising=False)
    payload = config_to_json_dict(ConfigManager._create_default_config())
    assert set(payload["paths"]) == {"appDataDir", "cookiesFile"}


def test_config_resource_includes_user_data_dir_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XHS_USER_DATA_DIR", "/tmp/xhs-profile")
    payload = config_to_json_dict(ConfigManager._create_default_config())
    assert payload["paths"]["userDataDir"] == "/tmp/xhs-profile"


def test_is_profile_mode_follows_config(profile_dir: Path) -> None:
    assert is_profile_mode() is True
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


def test_clear_is_a_no_op_in_cookie_file_mode(tmp_path: Path) -> None:
    original = config_module.get_config()
    config_module.set_config(
        replace(original, paths=replace(original.paths, user_data_dir=None))
    )
    try:
        assert clear_user_data_dir() == (False, None)
    finally:
        config_module.set_config(original)


# ----------------------------------------------------------------------
# Logout integration
# ----------------------------------------------------------------------


async def test_logout_reports_profile_cleared(profile_dir: Path) -> None:
    from xhs_mcp.core.auth.auth_service import AuthService

    ensure_user_data_dir(str(profile_dir))
    result = await AuthService(config_module.get_config()).logout()

    assert result["success"] is True
    assert result["profileCleared"] is True
    assert "browser profile deleted" in result["message"]
    assert not profile_dir.exists()


async def test_logout_reports_when_profile_was_kept(profile_dir: Path) -> None:
    from xhs_mcp.core.auth.auth_service import AuthService

    profile_dir.mkdir(parents=True)  # no marker

    result = await AuthService(config_module.get_config()).logout()

    assert result["success"] is True
    assert result["profileCleared"] is False
    assert "Refused to delete browser profile" in result["message"]
    assert profile_dir.exists()


async def test_logout_payload_unchanged_in_cookie_file_mode(tmp_path: Path) -> None:
    """Default mode must not gain a profileCleared key."""
    from xhs_mcp.core.auth.auth_service import AuthService

    original = config_module.get_config()
    config_module.set_config(
        replace(
            original,
            paths=replace(
                original.paths,
                cookies_file=str(tmp_path / "cookies.json"),
                user_data_dir=None,
            ),
        )
    )
    try:
        result = await AuthService(config_module.get_config()).logout()
        assert result == {
            "success": True,
            "message": "Logged out successfully (cookies deleted)",
            "status": "logged_out",
            "action": "logged_out",
        }
    finally:
        config_module.set_config(original)
