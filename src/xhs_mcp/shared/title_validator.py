"""Title validation for XHS MCP Server.

XiaoHongShu measures titles by display width, not character count:

- maximum width: 40 units
- CJK characters: 2 units each
- other characters (English/numbers): 1 unit each

Widths come from :mod:`xhs_mcp.shared.string_width`, which reproduces npm
``string-width@8`` exactly.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from .errors import PublishError
from .string_width import string_width


class TitleValidationResult(TypedDict, total=False):
    valid: bool
    width: int
    maxWidth: int
    message: str
    suggestion: str


class XHSTitleConstraints:
    MAX_WIDTH = 40
    """Maximum display width in units."""

    MAX_LENGTH = 20
    """Approximate max character count (for reference)."""


# Alias matching the TypeScript export name.
XHS_TITLE_CONSTRAINTS = XHSTitleConstraints


def validate_title_width(title: str) -> TitleValidationResult:
    """Validate a title against XHS display width rules.

    >>> validate_title_width("Hello世界")["width"]
    9
    """
    if not title:
        return {
            "valid": False,
            "width": 0,
            "maxWidth": XHSTitleConstraints.MAX_WIDTH,
            "message": "Title cannot be empty",
            "suggestion": "Please provide a valid title",
        }

    width = string_width(title)

    if width > XHSTitleConstraints.MAX_WIDTH:
        return {
            "valid": False,
            "width": width,
            "maxWidth": XHSTitleConstraints.MAX_WIDTH,
            "message": (
                f"Title width exceeds limit: {width} units "
                f"(max: {XHSTitleConstraints.MAX_WIDTH} units)"
            ),
            "suggestion": (
                "Current title is too long. CJK characters count as 2 units, "
                "English/numbers as 1 unit. Please shorten your title."
            ),
        }

    return {
        "valid": True,
        "width": width,
        "maxWidth": XHSTitleConstraints.MAX_WIDTH,
    }


def assert_title_width_valid(title: str) -> None:
    """Raise :class:`PublishError` when the title is empty or too wide."""
    result = validate_title_width(title)

    if not result["valid"]:
        raise PublishError(
            result["message"],
            {
                "title": title,
                "width": result["width"],
                "maxWidth": result["maxWidth"],
                "suggestion": result.get("suggestion"),
                "details": {
                    "titleLength": len(title),
                    "displayWidth": result["width"],
                    "maxDisplayWidth": result["maxWidth"],
                    "exceeded": result["width"] - result["maxWidth"],
                },
            },
        )


def get_title_width(title: str) -> int:
    """Return the display width of ``title`` in units.

    >>> get_title_width("Hello")
    5
    >>> get_title_width("你好")
    4
    """
    return string_width(title)


def calculate_remaining_title_width(title: str) -> int:
    """Return how many width units are still available."""
    return max(0, XHSTitleConstraints.MAX_WIDTH - get_title_width(title))


def truncate_title_to_width(
    title: str, max_width: int = XHSTitleConstraints.MAX_WIDTH
) -> str:
    """Truncate ``title`` so it fits within ``max_width`` units."""
    if get_title_width(title) <= max_width:
        return title

    truncated = ""
    current_width = 0

    for char in title:
        char_width = string_width(char)

        if current_width + char_width > max_width:
            break

        truncated += char
        current_width += char_width

    return truncated


CharType = Literal["CJK", "ASCII", "Emoji", "Other"]

_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF))
_EMOJI_RANGE = (0x1F300, 0x1F9FF)


def _classify_char(char: str) -> CharType:
    code = ord(char[0])

    if any(low <= code <= high for low, high in _CJK_RANGES):
        return "CJK"
    if code < 128:
        return "ASCII"
    if _EMOJI_RANGE[0] <= code <= _EMOJI_RANGE[1]:
        return "Emoji"
    return "Other"


def get_title_width_breakdown(title: str) -> dict[str, Any]:
    """Return a per-character width breakdown, useful for debugging and feedback."""
    total_width = get_title_width(title)

    breakdown = [
        {"char": char, "width": string_width(char), "type": _classify_char(char)}
        for char in title
    ]

    return {
        "title": title,
        "totalWidth": total_width,
        "totalChars": len(title),
        "maxWidth": XHSTitleConstraints.MAX_WIDTH,
        "remaining": calculate_remaining_title_width(title),
        "valid": total_width <= XHSTitleConstraints.MAX_WIDTH,
        "breakdown": breakdown,
    }
