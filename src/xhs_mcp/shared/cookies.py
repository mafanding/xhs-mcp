"""Legacy cookie-file support.

Earlier versions (and the TypeScript implementation this was ported from) kept
the session in a JSON array at ``~/.xhs-mcp/cookies.json`` and re-injected it
into a fresh, incognito-like browser context on every run. That pattern is a
strong automation signal — a real user's browser is never a brand-new private
window each time — so the session now lives in a persistent Chromium profile
instead (see :mod:`xhs_mcp.shared.profile`).

What remains here is a **one-way import**: if an old cookie file is still
present when a fresh profile starts up, it is read once to seed the profile so
nobody has to log in again. Nothing is ever written back to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import get_config
from .logger import logger
from .types import Cookie


def get_cookies_file_path() -> str:
    """Path of the legacy cookie file (read-only; kept for migration)."""
    return get_config().paths.cookies_file


def has_legacy_cookies() -> bool:
    return Path(get_cookies_file_path()).exists()


def load_cookies() -> list[Cookie] | None:
    """Read the legacy cookie file, or ``None`` when absent or unreadable."""
    path = Path(get_cookies_file_path())

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        logger.error(f"Invalid JSON in cookies file {path}: {error}")
        return None
    except OSError as error:
        logger.error(f"Failed to read cookies from {path}: {error}")
        return None


def delete_cookies_file() -> bool:
    """Remove the legacy cookie file. Absent is treated as success."""
    path = Path(get_cookies_file_path())

    if not path.exists():
        return True

    try:
        path.unlink()
        return True
    except OSError as error:
        logger.error(f"Failed to delete cookies file {path}: {error}")
        return False
