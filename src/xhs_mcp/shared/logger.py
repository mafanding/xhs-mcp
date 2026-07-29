"""Logger for XHS MCP Server.

Everything goes to stderr and only when ``XHS_ENABLE_LOGGING=true``. In stdio
mode stdout carries the JSON-RPC framing, so a single stray byte there breaks
every MCP client; keeping this module the only writer keeps that safe.
"""

from __future__ import annotations

import os
import sys
from typing import Any


class Logger:
    """Minimal stderr logger gated on ``XHS_ENABLE_LOGGING``."""

    _instance: Logger | None = None

    def __init__(self) -> None:
        self.enabled = os.environ.get("XHS_ENABLE_LOGGING") == "true"

    @classmethod
    def get_instance(cls) -> Logger:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _write(self, level: str, message: str, *args: Any) -> None:
        if not self.enabled:
            return
        extra = " ".join(str(arg) for arg in args)
        line = f"[{level}] {message}{' ' + extra if extra else ''}"
        print(line, file=sys.stderr, flush=True)

    def debug(self, message: str, *args: Any) -> None:
        self._write("DEBUG", message, *args)

    def info(self, message: str, *args: Any) -> None:
        self._write("INFO", message, *args)

    def warn(self, message: str, *args: Any) -> None:
        self._write("WARN", message, *args)

    def error(self, message: str, *args: Any) -> None:
        self._write("ERROR", message, *args)


logger = Logger.get_instance()
