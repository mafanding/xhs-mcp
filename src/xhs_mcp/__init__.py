"""XHS MCP Server — XiaoHongShu CLI and Model Context Protocol server.

Python implementation driving a stealth Chromium via CloakBrowser.
"""

from .core import (
    AuthService,
    BrowserManager,
    DeleteService,
    FeedService,
    NoteService,
    PublishService,
)
from .server import XHSHTTPMCPServer, XHSMCPServer
from .shared import Config, XHSError, get_config

__all__ = [
    "AuthService",
    "BrowserManager",
    "Config",
    "DeleteService",
    "FeedService",
    "NoteService",
    "PublishService",
    "XHSError",
    "XHSHTTPMCPServer",
    "XHSMCPServer",
    "get_config",
]
