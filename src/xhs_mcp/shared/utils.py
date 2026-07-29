"""Common utility functions for XHS MCP Server."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


async def sleep(ms: float) -> None:
    """Sleep for ``ms`` milliseconds (the TypeScript original works in ms)."""
    await asyncio.sleep(ms / 1000)


def safe_error_handler(error: BaseException | str, context: str, log: Any) -> None:
    """Log an error without re-raising."""
    message = str(error)
    log.error(f"{context}: {message}")


def validate_required_params(params: dict[str, Any], required_keys: list[str]) -> None:
    """Raise if any required parameter is missing, ``None`` or empty string."""
    missing = [key for key in required_keys if params.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing required parameters: {', '.join(missing)}")


def omit_none(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Drop the named keys from ``payload`` when their value is ``None``.

    ``JSON.stringify`` omits properties whose value is ``undefined``, so the
    TypeScript implementation emitted no key at all for an absent ``noteId``,
    ``profile``, ``nextCursor``, ``code`` or ``lastModified``. Python would
    serialise those as ``null``, which changes the payload for any client doing
    an ``in``/``hasOwnProperty`` check. Only the listed keys are considered, so
    a deliberate ``null`` — such as ``DeleteResult.data`` — is preserved.
    """
    return {
        key: value
        for key, value in payload.items()
        if not (key in keys and value is None)
    }


def is_string(value: Any) -> bool:
    """Type guard mirroring the TypeScript ``isString`` helper."""
    return isinstance(value, str)


def is_number(value: Any) -> bool:
    """Type guard mirroring ``isNumber``: numeric and not NaN (``bool`` excluded)."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return value == value  # NaN is the only value that fails this


def is_array(value: Any) -> bool:
    """Type guard mirroring the TypeScript ``isArray`` helper."""
    return isinstance(value, list)


def safe_json_parse(json_string: str, fallback: T) -> T:
    try:
        return json.loads(json_string)
    except (ValueError, TypeError):
        return fallback


def validate_publish_note_params(title: str, note: str, image_paths: list[str]) -> None:
    """Validate publish constraints: title <= 20 chars, note <= 1000, <= 18 images."""
    if title and len(title) > 20:
        raise ValueError(f"Title length cannot exceed 20 characters. Current length: {len(title)}")

    if note and len(note) > 1000:
        raise ValueError(
            f"Note content length cannot exceed 1000 characters. Current length: {len(note)}"
        )

    if image_paths and len(image_paths) > 18:
        raise ValueError(f"Maximum 18 images allowed. Current count: {len(image_paths)}")


def create_api_response(
    success: bool,
    data: Any = None,
    message: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {"success": success}
    if data is not None:
        response["data"] = data
    if message is not None:
        response["message"] = message
    if error is not None:
        response["error"] = error
    return response


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    base_delay: float = 1000,
) -> T:
    """Retry ``fn`` with exponential backoff (delays in milliseconds)."""
    last_error: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except BaseException as error:  # noqa: BLE001 - re-raised below
            last_error = error
            if attempt == max_retries:
                raise
            await sleep(base_delay * (2**attempt))

    assert last_error is not None
    raise last_error


def create_mcp_tool_response(data: Any) -> dict[str, Any]:
    """Wrap ``data`` in the MCP ``{content: [{type, text}]}`` envelope."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, indent=2, default=str),
            }
        ]
    }


def create_mcp_error_response(error: Any) -> dict[str, Any]:
    error_data = {
        "success": False,
        "error": "UnknownError",
        "message": str(error),
    }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(error_data, ensure_ascii=False, indent=2),
            }
        ]
    }
