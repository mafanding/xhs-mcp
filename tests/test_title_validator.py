"""Title width validation, mirroring tests/integration/title-validation.test.js."""

from __future__ import annotations

import pytest

from xhs_mcp.shared.errors import PublishError
from xhs_mcp.shared.title_validator import (
    XHSTitleConstraints,
    assert_title_width_valid,
    calculate_remaining_title_width,
    get_title_width,
    get_title_width_breakdown,
    truncate_title_to_width,
    validate_title_width,
)


@pytest.mark.parametrize(
    ("title", "expected_width", "expected_valid"),
    [
        ("Hello World", 11, True),
        ("你好世界", 8, True),
        ("Hello世界", 9, True),
        ("👋Hello世界🌍", 13, True),
        ("这是一个很长的标题", 18, True),
        ("这是一个非常非常非常非常非常长的标题", 36, True),
        ("A" * 50, 50, False),
        ("中" * 25, 50, False),
        ("今日美食分享", 12, True),
        ("春天来了🌸", 10, True),
        ("My Travel Diary", 15, True),
        ("2024年终总结报告", 16, True),
        ("iPhone 15 Pro Max开箱", 21, True),
        ("如何在30天内学会编程", 20, True),
    ],
)
def test_validate_title_width(title: str, expected_width: int, expected_valid: bool) -> None:
    result = validate_title_width(title)
    assert result["width"] == expected_width
    assert result["valid"] is expected_valid
    assert result["maxWidth"] == XHSTitleConstraints.MAX_WIDTH


def test_empty_title_is_invalid() -> None:
    result = validate_title_width("")
    assert result["valid"] is False
    assert result["width"] == 0
    assert result["message"] == "Title cannot be empty"
    assert result["suggestion"] == "Please provide a valid title"


def test_exactly_at_limit_is_valid() -> None:
    title = "中" * 20  # 40 units
    assert get_title_width(title) == 40
    assert validate_title_width(title)["valid"] is True


def test_one_unit_over_limit_is_invalid() -> None:
    title = "中" * 20 + "A"  # 41 units
    result = validate_title_width(title)
    assert result["valid"] is False
    assert result["message"] == "Title width exceeds limit: 41 units (max: 40 units)"


def test_whitespace_only_titles() -> None:
    assert validate_title_width(" ")["width"] == 1
    assert validate_title_width("   ")["width"] == 3
    # Control characters have zero width, so this is treated as an empty title.
    assert validate_title_width("\n\t")["width"] == 0


def test_many_emojis_hits_the_limit_exactly() -> None:
    assert validate_title_width("🎉" * 20)["width"] == 40


def test_assert_title_width_valid_passes_for_valid_title() -> None:
    assert_title_width_valid("正常标题")


def test_assert_title_width_valid_raises_with_context() -> None:
    long_title = "中" * 25

    with pytest.raises(PublishError) as excinfo:
        assert_title_width_valid(long_title)

    error = excinfo.value
    assert error.error_code == "PublishError"
    assert error.context["width"] == 50
    assert error.context["maxWidth"] == 40
    assert error.context["details"]["exceeded"] == 10


def test_assert_title_width_valid_raises_for_empty_title() -> None:
    with pytest.raises(PublishError, match="Title cannot be empty"):
        assert_title_width_valid("")


def test_calculate_remaining_title_width() -> None:
    assert calculate_remaining_title_width("Hello") == 35
    assert calculate_remaining_title_width("中" * 20) == 0
    # Never negative, even when already over the limit.
    assert calculate_remaining_title_width("中" * 30) == 0


def test_truncate_title_to_width() -> None:
    long_title = "这是一个很长很长的标题" * 5
    truncated = truncate_title_to_width(long_title)
    assert get_title_width(truncated) <= XHSTitleConstraints.MAX_WIDTH


def test_truncate_leaves_short_titles_untouched() -> None:
    assert truncate_title_to_width("短标题") == "短标题"


def test_truncate_never_splits_a_wide_character() -> None:
    # 39 units available, so the final 2-unit character must be dropped whole.
    title = "A" + "中" * 20
    truncated = truncate_title_to_width(title)
    assert get_title_width(truncated) == 39
    assert truncated == "A" + "中" * 19


def test_get_title_width_breakdown() -> None:
    breakdown = get_title_width_breakdown("Hello世界👋ABC")

    assert breakdown["totalWidth"] == 14
    assert breakdown["valid"] is True
    assert breakdown["maxWidth"] == 40
    assert breakdown["remaining"] == 26

    types = {entry["char"]: entry["type"] for entry in breakdown["breakdown"]}
    assert types["H"] == "ASCII"
    assert types["世"] == "CJK"
    assert types["A"] == "ASCII"
