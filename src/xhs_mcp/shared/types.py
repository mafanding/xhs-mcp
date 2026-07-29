"""Type definitions for XHS MCP Server.

Configuration objects are frozen dataclasses; everything that crosses the MCP
or CLI boundary stays a plain ``dict`` so the JSON payloads keep the original
camelCase keys the TypeScript implementation emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

TransportMode = Literal["stdio", "sse", "streamable-http"]
AuthStatus = Literal["logged_in", "logged_out", "unknown"]
AuthAction = Literal["none", "logged_in", "logged_out", "failed"]
Visibility = Literal["public", "private", "friends", "unknown"]
FeedSource = Literal["home_page", "search", "detail"]
ContentType = Literal["image", "video"]


@dataclass(frozen=True)
class BrowserConfig:
    default_timeout: int
    login_timeout: int
    page_load_timeout: int
    navigation_timeout: int
    slowmo: int
    headless_default: bool


@dataclass(frozen=True)
class ServerConfig:
    name: str
    version: str
    description: str
    default_host: str
    default_port: int
    default_transport: TransportMode


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    format: str
    file_enabled: bool
    file_path: str | None = None


@dataclass(frozen=True)
class PathsConfig:
    app_data_dir: str
    cookies_file: str
    user_data_dir: str | None = None
    """Persistent Chromium profile directory, or ``None`` for a fresh context per run.

    Set via ``XHS_USER_DATA_DIR``. When present the browser keeps cookies,
    localStorage and IndexedDB across runs instead of starting incognito-like
    each time.
    """


@dataclass(frozen=True)
class XHSConfig:
    home_url: str
    explore_url: str
    search_url: str
    creator_publish_url: str
    creator_video_publish_url: str
    login_ok_selector: str
    request_delay: float
    max_retries: int
    retry_delay: float


@dataclass(frozen=True)
class Config:
    browser: BrowserConfig
    server: ServerConfig
    logging: LoggingConfig
    paths: PathsConfig
    xhs: XHSConfig


class Cookie(TypedDict, total=False):
    """HTTP cookie as persisted in ``~/.xhs-mcp/cookies.json``."""

    name: str
    value: str
    domain: str
    path: str
    expires: float
    httpOnly: bool
    secure: bool
    sameSite: str


class CookiesInfo(TypedDict, total=False):
    filePath: str
    fileExists: bool
    cookieCount: int
    lastModified: float | None


# Result payloads are emitted as plain dicts to preserve the exact camelCase key
# names of the TypeScript implementation. These aliases document intent at the
# call sites without constraining the shape.
XHSResponse = dict[str, Any]
LoginResult = dict[str, Any]
StatusResult = dict[str, Any]
UserProfile = dict[str, Any]
FeedItem = dict[str, Any]
FeedListResult = dict[str, Any]
SearchResult = dict[str, Any]
FeedDetailResult = dict[str, Any]
CommentResult = dict[str, Any]
PublishResult = dict[str, Any]
UserNote = dict[str, Any]
UserNotesResult = dict[str, Any]
DeleteResult = dict[str, Any]
ServerStatus = dict[str, Any]
