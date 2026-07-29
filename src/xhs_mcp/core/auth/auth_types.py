"""Authentication-related types for XHS MCP Server."""

from __future__ import annotations

from typing import TypedDict

from ...shared.types import AuthAction, AuthStatus

__all__ = ["AuthAction", "AuthStatus", "LoginOptions", "StatusCheckOptions"]


class LoginOptions(TypedDict, total=False):
    browserPath: str
    timeout: int


class StatusCheckOptions(TypedDict, total=False):
    browserPath: str
    quick: bool
