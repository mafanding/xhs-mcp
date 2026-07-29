"""Feed-related types for XHS MCP Server."""

from __future__ import annotations

from typing import TypedDict

from ...shared.types import FeedSource

__all__ = [
    "CommentOptions",
    "FeedDetailOptions",
    "FeedListOptions",
    "FeedSource",
    "SearchOptions",
]


class FeedListOptions(TypedDict, total=False):
    browserPath: str


class SearchOptions(TypedDict, total=False):
    keyword: str
    browserPath: str


class FeedDetailOptions(TypedDict, total=False):
    feedId: str
    xsecToken: str
    browserPath: str


class CommentOptions(TypedDict, total=False):
    feedId: str
    xsecToken: str
    note: str
    browserPath: str
