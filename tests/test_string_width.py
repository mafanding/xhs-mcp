"""Verify string_width against an oracle generated from npm ``string-width@8``.

``tests/width_oracle.json`` was produced by running the real npm package over a
corpus covering CJK, emoji (including ZWJ sequences, flags and skin tones),
combining marks, fullwidth forms, ambiguous-width characters and ANSI escapes.
Title validation depends on matching it exactly, since the width limit decides
which titles XiaoHongShu accepts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xhs_mcp.shared.string_width import string_width

_ORACLE = json.loads((Path(__file__).parent / "width_oracle.json").read_text())


def _decode(case: dict) -> str:
    return "".join(chr(code_point) for code_point in case["input"])


@pytest.mark.parametrize("case", _ORACLE, ids=lambda c: repr(_decode(c))[:40])
def test_whole_string_width_matches_oracle(case: dict) -> None:
    assert string_width(_decode(case)) == case["width"]


@pytest.mark.parametrize("case", _ORACLE, ids=lambda c: repr(_decode(c))[:40])
def test_per_code_point_width_matches_oracle(case: dict) -> None:
    text = _decode(case)
    for char, expected in zip(text, case["perChar"], strict=True):
        assert string_width(char) == expected, f"U+{ord(char):04X}"


def test_documented_examples() -> None:
    assert string_width("") == 0
    assert string_width("A") == 1
    assert string_width("中") == 2
    assert string_width("Hello") == 5
    assert string_width("你好") == 4
    assert string_width("A中B") == 4
    assert string_width("👋") == 2


def test_ansi_escape_codes_are_stripped_by_default() -> None:
    assert string_width("\x1b[31mred\x1b[0m") == 3


def test_non_string_input_is_zero() -> None:
    assert string_width(None) == 0  # type: ignore[arg-type]
