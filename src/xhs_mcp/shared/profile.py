"""Persistent Chromium profile directory management.

When ``XHS_USER_DATA_DIR`` is set the browser runs against a real Chrome user
data directory instead of a fresh, incognito-like context per run. That keeps
cookies, localStorage and IndexedDB across runs and stops the session looking
like a brand-new private window to XiaoHongShu's risk checks.

``logout`` has to be able to wipe that directory — deleting ``cookies.json``
alone would leave the profile logged in. Since the path comes from user-supplied
configuration and could plausibly be pointed at a real Chrome profile, a
directory is only ever deleted when it carries the marker file this module
writes.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_config
from .logger import logger

MARKER_FILENAME = ".xhs-mcp-profile"
"""Marks a profile directory as created and owned by xhs-mcp."""

_COOKIES_DB_RELATIVE = ("Default", "Cookies")


def get_user_data_dir() -> str:
    """Return the Chromium profile directory holding the session."""
    return get_config().paths.user_data_dir


def ensure_user_data_dir(path: str) -> None:
    """Create the profile directory and stamp it as ours.

    The marker is what later authorises :func:`clear_user_data_dir` to delete
    the directory, so it is written before the browser ever launches.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)

    marker = directory / MARKER_FILENAME
    if not marker.exists():
        marker.write_text(
            json.dumps(
                {
                    "createdBy": "xhs-mcp",
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "note": (
                        "Marks this directory as an xhs-mcp browser profile. "
                        "Removing this file will make `xhs-mcp logout` refuse to "
                        "delete the directory."
                    ),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def is_owned_profile(path: str) -> bool:
    """Return True when ``path`` carries this module's marker file."""
    return (Path(path) / MARKER_FILENAME).exists()


def count_profile_cookies(path: str | None = None) -> int | None:
    """Count cookies stored in the profile, or ``None`` if that isn't readable.

    Chromium keeps them in a SQLite database that is locked while the browser
    runs, so the file is copied before reading.

    The figure reflects what is **on disk**. Chromium buffers cookies in memory
    and flushes periodically, so while a browser is live this can read low (or
    zero) even though the session is valid; it settles once the browser exits.
    Informational only — nothing decides behaviour from it.
    """
    directory = Path(path or get_user_data_dir())
    db_path = directory.joinpath(*_COOKIES_DB_RELATIVE)

    if not db_path.exists():
        return None

    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "Cookies"
            shutil.copy2(db_path, copy)
            connection = sqlite3.connect(copy)
            try:
                return int(connection.execute("SELECT count(*) FROM cookies").fetchone()[0])
            finally:
                connection.close()
    except (OSError, sqlite3.Error) as error:
        logger.debug(f"Could not read profile cookie database: {error}")
        return None


def get_profile_info() -> dict[str, Any]:
    """Describe the session store, for the ``xhs://cookies`` resource."""
    path = get_user_data_dir()
    directory = Path(path)
    exists = directory.is_dir()

    info: dict[str, Any] = {
        "profileDir": path,
        "profileExists": exists,
        "cookieCount": 0,
    }

    if not exists:
        return info

    cookie_count = count_profile_cookies(path)
    if cookie_count is not None:
        info["cookieCount"] = cookie_count

    db_path = directory.joinpath(*_COOKIES_DB_RELATIVE)
    if db_path.exists():
        # Milliseconds since the epoch, matching JavaScript's Date#getTime().
        info["lastModified"] = db_path.stat().st_mtime * 1000

    return info


def clear_user_data_dir() -> tuple[bool, str | None]:
    """Delete the profile directory during logout.

    Returns ``(cleared, message)``. Refuses — rather than deleting — any
    directory without the marker file, so pointing ``XHS_USER_DATA_DIR`` at a
    real Chrome profile can never destroy it.
    """
    path = get_user_data_dir()

    directory = Path(path)
    if not directory.exists():
        return True, None

    if not is_owned_profile(path):
        message = (
            f"Refused to delete browser profile {path}: it was not created by "
            f"xhs-mcp (no {MARKER_FILENAME} marker). Delete it manually if you "
            f"are sure, or unset XHS_USER_DATA_DIR."
        )
        logger.warn(message)
        return False, message

    try:
        shutil.rmtree(directory)
        logger.info(f"Removed browser profile {path}")
        return True, None
    except OSError as error:
        message = f"Failed to remove browser profile {path}: {error}"
        logger.error(message)
        return False, message
