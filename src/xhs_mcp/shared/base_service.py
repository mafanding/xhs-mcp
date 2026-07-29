"""Base class shared by all XHS domain services."""

from __future__ import annotations

from ..core.browser.browser_manager import BrowserManager
from .types import Config


class BaseService:
    """Holds the configuration and the browser manager a service operates through."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        self.config = config
        self.browser_manager = browser_manager or BrowserManager(config)

    def get_browser_manager(self) -> BrowserManager:
        return self.browser_manager

    def get_config(self) -> Config:
        return self.config
