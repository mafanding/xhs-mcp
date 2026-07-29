"""Browser-related types for XHS MCP Server."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict


class BrowserLaunchOptions(TypedDict, total=False):
    headless: bool
    executablePath: str
    slowMo: int
    args: list[str]


class PageOptions(TypedDict, total=False):
    loadCookies: bool
    headless: bool
    executablePath: str
    timeout: int
    navigationTimeout: int


@dataclass
class ManagedBrowser:
    """A pooled browser together with its context and health bookkeeping."""

    browser: Any
    context: Any
    id: str
    created_at: datetime
    last_used: datetime
    is_available: bool = True
    is_healthy: bool = True
    usage_count: int = 0
    playwright: Any = None


class BrowserPoolStats(TypedDict):
    totalInstances: int
    availableInstances: int
    busyInstances: int
    unhealthyInstances: int
    totalUsage: int
    averageAge: float
    oldestInstance: str | None
    newestInstance: str | None


@dataclass
class BrowserPoolOptions:
    min_instances: int = 2
    max_instances: int = 5
    idle_timeout: int = 300_000
    max_age: int = 1_800_000
    health_check_interval: int = 60_000
    max_usage_count: int = 100
    stuck_timeout: int = 600_000
    extra: dict[str, Any] = field(default_factory=dict)
