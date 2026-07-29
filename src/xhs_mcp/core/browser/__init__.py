"""Browser management for XHS MCP Server."""

from .browser_manager import (
    BrowserManager,
    cleanup_global_browser_manager,
    get_browser_manager,
    get_pooled_browser_manager,
)
from .browser_pool_service import (
    BrowserPoolService,
    cleanup_browser_pool,
    get_browser_pool,
)
from .browser_types import (
    BrowserLaunchOptions,
    BrowserPoolOptions,
    BrowserPoolStats,
    ManagedBrowser,
    PageOptions,
)
from .session_manager import (
    BrowserSession,
    BrowserSessionManager,
    get_session_manager,
    read_devtools_endpoint,
)

__all__ = [
    "BrowserLaunchOptions",
    "BrowserSession",
    "BrowserSessionManager",
    "BrowserManager",
    "BrowserPoolOptions",
    "BrowserPoolService",
    "BrowserPoolStats",
    "ManagedBrowser",
    "PageOptions",
    "cleanup_browser_pool",
    "cleanup_global_browser_manager",
    "get_browser_manager",
    "get_browser_pool",
    "get_pooled_browser_manager",
    "get_session_manager",
    "read_devtools_endpoint",
]
