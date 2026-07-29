"""Display-width measurement compatible with the npm ``string-width`` package.

The TypeScript implementation this project is ported from measured XiaoHongShu
title widths with ``string-width@8``. This module reproduces that algorithm so
titles accepted (or rejected) here match the original byte for byte:

1. ANSI escape sequences are stripped.
2. The string is split into grapheme clusters.
3. For each cluster the *first* code point decides the width, except that a
   cluster which is an emoji always counts as 2.
4. Control characters, zero-width characters, combining marks and
   default-ignorable code points count as 0.
5. East Asian Wide/Fullwidth count as 2, everything else (including East Asian
   Ambiguous, because ``ambiguousIsNarrow`` defaults to true) counts as 1.
"""

from __future__ import annotations

import unicodedata

import regex

# Matches CSI / OSC style escape sequences, mirroring npm ``ansi-regex``.
_ANSI_RE = regex.compile(
    r"[][[\]()#;?]*"
    r"(?:(?:(?:(?:;[-a-zA-Z\d\/#&.:=?%@~_]+)*|[a-zA-Z\d]+(?:;[-a-zA-Z\d\/#&.:=?%@~_]*)*)?"
    r")|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))"
)

_GRAPHEME_RE = regex.compile(r"\X")
_DEFAULT_IGNORABLE_RE = regex.compile(r"^\p{Default_Ignorable_Code_Point}$")
_EXTENDED_PICTOGRAPHIC_RE = regex.compile(r"\p{Extended_Pictographic}")
_EMOJI_PRESENTATION_RE = regex.compile(r"\p{Emoji_Presentation}")
_REGIONAL_INDICATOR_RE = regex.compile(r"\p{Regional_Indicator}")

_ZWJ = "‍"
_VARIATION_SELECTOR_16 = "️"


def _is_emoji_cluster(cluster: str) -> bool:
    """Approximate ``emoji-regex``'s RGI_Emoji test over a grapheme cluster.

    ``string-width`` calls ``emojiRegex().test(character)``, which is unanchored:
    a cluster counts as an emoji if it *contains* an RGI emoji sequence. The
    cases that matter in practice are:

    - flag sequences built from two regional indicators
    - ZWJ sequences such as the family emoji
    - text-presentation pictographs promoted to emoji by U+FE0F
    - pictographs that already default to emoji presentation

    A *lone* regional indicator is not a flag and stays narrow, matching
    ``emoji-regex``, which only accepts regional indicators in pairs.
    """
    if len(_REGIONAL_INDICATOR_RE.findall(cluster)) >= 2:
        return True

    if not _EXTENDED_PICTOGRAPHIC_RE.search(cluster):
        return False

    # A ZWJ sequence joining pictographs, or an explicit emoji-presentation
    # request via U+FE0F, is always rendered as an emoji.
    if _ZWJ in cluster or _VARIATION_SELECTOR_16 in cluster:
        return True

    # Otherwise only pictographs that default to emoji presentation qualify;
    # a bare text-presentation pictograph such as U+2122 (™) does not.
    return bool(_EMOJI_PRESENTATION_RE.match(cluster[0]))


def _is_zero_width(code_point: int, cluster: str) -> bool:
    # C0 and C1 control characters.
    if code_point <= 0x1F or 0x7F <= code_point <= 0x9F:
        return True

    # Explicit zero-width characters and the byte order mark.
    if 0x200B <= code_point <= 0x200F or code_point == 0xFEFF:
        return True

    # Combining diacritical marks.
    if 0x300 <= code_point <= 0x36F:
        return True

    return bool(_DEFAULT_IGNORABLE_RE.match(cluster[0]))


def string_width(text: str, *, count_ansi_escape_codes: bool = False) -> int:
    """Return the terminal display width of ``text``.

    Mirrors ``stringWidth(text)`` from npm ``string-width@8`` with its default
    options (``ambiguousIsNarrow: true``).
    """
    if not isinstance(text, str) or not text:
        return 0

    if not count_ansi_escape_codes:
        text = _ANSI_RE.sub("", text)

    if not text:
        return 0

    width = 0
    for cluster in _GRAPHEME_RE.findall(text):
        if not cluster:
            continue

        code_point = ord(cluster[0])

        if _is_zero_width(code_point, cluster):
            continue

        if _is_emoji_cluster(cluster):
            width += 2
            continue

        width += 2 if unicodedata.east_asian_width(cluster[0]) in ("F", "W") else 1

    return width
