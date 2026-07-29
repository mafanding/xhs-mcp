"""Configuration management for XHS MCP Server.

Environment variables, defaults and the ``~/.xhs-mcp`` layout follow the
TypeScript implementation so existing client configuration keeps working. The
one departure is where the session lives: a persistent browser profile at
``~/.xhs-mcp/profile`` rather than a ``cookies.json`` file — see
:mod:`xhs_mcp.shared.profile`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .types import (
    BrowserConfig,
    Config,
    LoggingConfig,
    PathsConfig,
    ServerConfig,
    XHSConfig,
)


def _resolve_package_version() -> str:
    """Resolve the installed distribution version, mirroring the package.json read."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("xhs-mcp")
        except PackageNotFoundError:
            pass
    except ImportError:
        pass

    return os.environ.get("XHS_VERSION", "0.1.0")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() == "true"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class ConfigManager:
    """Singleton holder for the application configuration."""

    _instance: ConfigManager | None = None

    def __init__(self) -> None:
        self._config = self._create_default_config()

    @classmethod
    def get_instance(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_config(self) -> Config:
        return self._config

    def update_config(self, **updates: Any) -> None:
        from dataclasses import replace

        self._config = replace(self._config, **updates)

    @staticmethod
    def _create_default_config() -> Config:
        app_data_dir = str(Path.home() / ".xhs-mcp")
        cookies_file = str(Path(app_data_dir) / "cookies.json")

        browser = BrowserConfig(
            default_timeout=_env_int("XHS_BROWSER_TIMEOUT", 30000),
            login_timeout=_env_int("XHS_LOGIN_TIMEOUT", 300),
            page_load_timeout=30000,
            navigation_timeout=30000,
            slowmo=0,
            headless_default=_env_flag("XHS_HEADLESS", True),
        )

        server = ServerConfig(
            name=os.environ.get("XHS_SERVER_NAME", "xhs-mcp"),
            version=_resolve_package_version(),
            description="XiaoHongShu MCP Server - Python Version",
            default_host=os.environ.get("XHS_HOST", "127.0.0.1"),
            default_port=_env_int("XHS_PORT", 8000),
            default_transport="stdio",
        )

        log_file_enabled = _env_flag("XHS_LOG_FILE", False)
        logging_config = LoggingConfig(
            level=os.environ.get("XHS_LOG_LEVEL", "INFO"),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            file_enabled=log_file_enabled,
            file_path=str(Path(app_data_dir) / "xhs-mcp.log") if log_file_enabled else None,
        )

        raw_user_data_dir = os.environ.get("XHS_USER_DATA_DIR", "").strip()
        paths = PathsConfig(
            app_data_dir=app_data_dir,
            cookies_file=cookies_file,
            user_data_dir=(
                str(Path(raw_user_data_dir).expanduser())
                if raw_user_data_dir
                else str(Path(app_data_dir) / "profile")
            ),
        )

        xhs = XHSConfig(
            home_url="https://www.xiaohongshu.com",
            explore_url="https://www.xiaohongshu.com/explore",
            search_url="https://www.xiaohongshu.com/search_result",
            creator_publish_url="https://creator.xiaohongshu.com/publish/publish?source=official",
            creator_video_publish_url=(
                "https://creator.xiaohongshu.com/publish/publish"
                "?source=official&from=tab_switch&target=video"
            ),
            login_ok_selector=".main-container .user .link-wrapper .channel",
            request_delay=1.0,
            max_retries=3,
            retry_delay=2.0,
        )

        return Config(
            browser=browser,
            server=server,
            logging=logging_config,
            paths=paths,
            xhs=xhs,
        )

    def to_dict(self) -> dict[str, Any]:
        config = self._config
        return {
            "browser": {
                "defaultTimeout": config.browser.default_timeout,
                "loginTimeout": config.browser.login_timeout,
                "headlessDefault": config.browser.headless_default,
            },
            "server": {
                "name": config.server.name,
                "version": config.server.version,
                "defaultHost": config.server.default_host,
                "defaultPort": config.server.default_port,
            },
            "logging": {
                "level": config.logging.level,
                "fileEnabled": config.logging.file_enabled,
            },
            "paths": {
                "appDataDir": config.paths.app_data_dir,
                "userDataDir": config.paths.user_data_dir,
            },
            "xhs": {
                "homeUrl": config.xhs.home_url,
                "exploreUrl": config.xhs.explore_url,
                "maxRetries": config.xhs.max_retries,
            },
        }


_global_config: Config | None = None


def get_config() -> Config:
    global _global_config
    if _global_config is None:
        _global_config = ConfigManager.get_instance().get_config()
    return _global_config


def set_config(config: Config) -> None:
    global _global_config
    _global_config = config


def config_to_json_dict(config: Config) -> dict[str, Any]:
    """Render a :class:`Config` as the nested camelCase dict exposed via ``xhs://config``."""
    return {
        "browser": {
            "defaultTimeout": config.browser.default_timeout,
            "loginTimeout": config.browser.login_timeout,
            "pageLoadTimeout": config.browser.page_load_timeout,
            "navigationTimeout": config.browser.navigation_timeout,
            "slowmo": config.browser.slowmo,
            "headlessDefault": config.browser.headless_default,
        },
        "server": {
            "name": config.server.name,
            "version": config.server.version,
            "description": config.server.description,
            "defaultHost": config.server.default_host,
            "defaultPort": config.server.default_port,
            "defaultTransport": config.server.default_transport,
        },
        "logging": {
            "level": config.logging.level,
            "format": config.logging.format,
            "fileEnabled": config.logging.file_enabled,
            "filePath": config.logging.file_path,
        },
        "paths": {
            "appDataDir": config.paths.app_data_dir,
            "userDataDir": config.paths.user_data_dir,
        },
        "xhs": {
            "homeUrl": config.xhs.home_url,
            "exploreUrl": config.xhs.explore_url,
            "searchUrl": config.xhs.search_url,
            "creatorPublishUrl": config.xhs.creator_publish_url,
            "creatorVideoPublishUrl": config.xhs.creator_video_publish_url,
            "loginOkSelector": config.xhs.login_ok_selector,
            "requestDelay": config.xhs.request_delay,
            "maxRetries": config.xhs.max_retries,
            "retryDelay": config.xhs.retry_delay,
        },
    }
