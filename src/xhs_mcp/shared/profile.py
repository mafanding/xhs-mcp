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
from datetime import datetime, timezone
from pathlib import Path

from .config import get_config
from .logger import logger

MARKER_FILENAME = ".xhs-mcp-profile"
"""Marks a profile directory as created and owned by xhs-mcp."""


def get_user_data_dir() -> str | None:
    """Return the configured profile directory, or ``None`` in cookie-file mode."""
    return get_config().paths.user_data_dir


def is_profile_mode() -> bool:
    return get_user_data_dir() is not None


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


def clear_user_data_dir() -> tuple[bool, str | None]:
    """Delete the profile directory during logout.

    Returns ``(cleared, message)``. Refuses — rather than deleting — any
    directory without the marker file, so pointing ``XHS_USER_DATA_DIR`` at a
    real Chrome profile can never destroy it.
    """
    path = get_user_data_dir()

    if path is None:
        return False, None

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
