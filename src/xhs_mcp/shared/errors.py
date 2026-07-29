"""Error classes for XHS MCP Server.

The error *code* hierarchy deliberately mirrors the TypeScript original: each
subclass family passes a fixed literal code up to :class:`XHSError`, so the
leaf classes serialise under their family name. ``LoginTimeoutError`` reports
``"AuthenticationError"``, ``FeedNotFoundError`` reports ``"FeedError"``, and so
on. That code is part of the MCP wire format, so it must not drift to
``type(self).__name__``.
"""

from __future__ import annotations

from typing import Any


class XHSError(Exception):
    """Base error carrying a stable error code and structured context."""

    def __init__(
        self,
        message: str,
        error_code: str | None = None,
        context: dict[str, Any] | None = None,
        original_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code if error_code is not None else type(self).__name__
        self.context: dict[str, Any] = dict(context) if context else {}
        self.original_error = original_error

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the ``{success, error, message, context}`` MCP payload."""
        context: dict[str, Any] = dict(self.context)
        if self.original_error is not None:
            context["originalError"] = str(self.original_error)

        return {
            "success": False,
            "error": self.error_code,
            "message": self.message,
            "context": context,
        }

    def __str__(self) -> str:
        return self.message


class _FixedCodeError(XHSError):
    """Base for families whose subclasses all report the family's code."""

    _CODE = "XHSError"

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        original_error: BaseException | None = None,
    ) -> None:
        super().__init__(message, self._CODE, context, original_error)


class AuthenticationError(_FixedCodeError):
    _CODE = "AuthenticationError"


class LoginTimeoutError(AuthenticationError):
    pass


class LoginFailedError(AuthenticationError):
    pass


class NotLoggedInError(AuthenticationError):
    pass


class BrowserError(_FixedCodeError):
    _CODE = "BrowserError"


class BrowserLaunchError(BrowserError):
    pass


class BrowserNavigationError(BrowserError):
    pass


class FeedError(_FixedCodeError):
    _CODE = "FeedError"


class FeedNotFoundError(FeedError):
    pass


class FeedParsingError(FeedError):
    pass


class PublishError(_FixedCodeError):
    _CODE = "PublishError"


class InvalidImageError(PublishError):
    pass


class PublishFailedError(PublishError):
    pass


class NoteError(_FixedCodeError):
    _CODE = "NoteError"


class ProfileError(NoteError):
    pass


class NoteParsingError(NoteError):
    pass


class DeleteError(_FixedCodeError):
    _CODE = "DeleteError"
