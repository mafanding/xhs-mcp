"""Error code and serialisation behaviour.

The ``error`` field of :meth:`XHSError.to_dict` is part of the MCP wire format,
and in the TypeScript original every subclass reports its *family* name rather
than its own class name. These tests pin that down, because a from-scratch
Python port naturally gets it wrong.
"""

from __future__ import annotations

import pytest

from xhs_mcp.shared.errors import (
    AuthenticationError,
    BrowserError,
    BrowserLaunchError,
    BrowserNavigationError,
    DeleteError,
    FeedError,
    FeedNotFoundError,
    FeedParsingError,
    InvalidImageError,
    LoginFailedError,
    LoginTimeoutError,
    NoteError,
    NoteParsingError,
    NotLoggedInError,
    ProfileError,
    PublishError,
    PublishFailedError,
    XHSError,
)


@pytest.mark.parametrize(
    ("error_class", "expected_code"),
    [
        (AuthenticationError, "AuthenticationError"),
        (LoginTimeoutError, "AuthenticationError"),
        (LoginFailedError, "AuthenticationError"),
        (NotLoggedInError, "AuthenticationError"),
        (BrowserError, "BrowserError"),
        (BrowserLaunchError, "BrowserError"),
        (BrowserNavigationError, "BrowserError"),
        (FeedError, "FeedError"),
        (FeedNotFoundError, "FeedError"),
        (FeedParsingError, "FeedError"),
        (PublishError, "PublishError"),
        (InvalidImageError, "PublishError"),
        (PublishFailedError, "PublishError"),
        (NoteError, "NoteError"),
        (ProfileError, "NoteError"),
        (NoteParsingError, "NoteError"),
        (DeleteError, "DeleteError"),
    ],
)
def test_subclasses_report_their_family_code(
    error_class: type[XHSError], expected_code: str
) -> None:
    error = error_class("boom")
    assert error.error_code == expected_code
    assert error.to_dict()["error"] == expected_code


def test_base_error_defaults_to_class_name() -> None:
    assert XHSError("boom").error_code == "XHSError"


def test_explicit_error_code_wins() -> None:
    assert XHSError("boom", "CustomCode").error_code == "CustomCode"


def test_to_dict_shape() -> None:
    error = FeedParsingError("could not parse", {"feedId": "abc"})

    assert error.to_dict() == {
        "success": False,
        "error": "FeedError",
        "message": "could not parse",
        "context": {"feedId": "abc"},
    }


def test_to_dict_includes_original_error() -> None:
    cause = ValueError("underlying")
    error = PublishError("failed", {"title": "t"}, cause)

    payload = error.to_dict()
    assert payload["context"] == {"title": "t", "originalError": "underlying"}
    # The original context is not mutated.
    assert error.context == {"title": "t"}


def test_context_defaults_to_empty_dict() -> None:
    assert XHSError("boom").to_dict()["context"] == {}


def test_str_returns_message() -> None:
    assert str(DeleteError("Note ID is required")) == "Note ID is required"


def test_subclass_relationships_allow_family_catch() -> None:
    # Services rely on `except FeedError` also catching the two leaf types.
    with pytest.raises(FeedError):
        raise FeedNotFoundError("nope")
    with pytest.raises(FeedError):
        raise FeedParsingError("nope")
    with pytest.raises(AuthenticationError):
        raise NotLoggedInError("nope")
    with pytest.raises(XHSError):
        raise DeleteError("nope")
