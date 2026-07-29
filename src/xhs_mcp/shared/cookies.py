"""Cookie management for XHS MCP Server.

The on-disk format is unchanged from the TypeScript implementation — a JSON
array at ``~/.xhs-mcp/cookies.json`` — so a profile created by either version
works with the other.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import get_config
from .errors import XHSError
from .logger import logger
from .types import Cookie, CookiesInfo
from .utils import omit_none


def get_cookies_file_path() -> str:
    return get_config().paths.cookies_file


def load_cookies() -> list[Cookie] | None:
    """Load persisted cookies, or ``None`` when absent or unreadable."""
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


def save_cookies(cookies: list[Cookie]) -> None:
    """Persist cookies, creating the parent directory as needed.

    An empty list is a no-op: the original never overwrote a good cookie file
    with an empty one.
    """
    if not cookies:
        return

    path = Path(get_cookies_file_path())

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        logger.error(f"Failed to save cookies to {path}: {error}")
        raise XHSError(
            f"Failed to save cookies: {error}", "CookieSaveError", {}, error
        ) from error


def delete_cookies_file() -> bool:
    path = Path(get_cookies_file_path())

    if not path.exists():
        return True

    try:
        path.unlink()
        return True
    except OSError as error:
        logger.error(f"Failed to delete cookies file {path}: {error}")
        return False


def get_cookies_info() -> CookiesInfo:
    path = Path(get_cookies_file_path())
    cookies = load_cookies()

    last_modified: float | None = None
    exists = path.exists()
    if exists:
        # Milliseconds since the epoch, matching JavaScript's Date#getTime().
        last_modified = path.stat().st_mtime * 1000

    return omit_none(
        {
            "filePath": str(path),
            "fileExists": exists,
            "cookieCount": len(cookies) if cookies else 0,
            "lastModified": last_modified,
        },
        "lastModified",
    )
