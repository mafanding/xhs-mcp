"""Publishing-related types for XHS MCP Server."""

from __future__ import annotations

from typing import TypedDict


class PublishOptions(TypedDict, total=False):
    title: str
    note: str
    imagePaths: list[str]
    tags: str
    browserPath: str


class ImageValidationResult(TypedDict, total=False):
    valid: bool
    resolvedPath: str
    originalPath: str
    error: str


class UploadTabInfo(TypedDict):
    text: str
    selector: str


class VideoPublishOptions(TypedDict, total=False):
    title: str
    content: str
    videoPath: str
    tags: str
    browserPath: str


class VideoValidationResult(TypedDict, total=False):
    valid: bool
    resolvedPath: str
    originalPath: str
    error: str
