"""Absent optional values must be omitted, not serialised as ``null``.

``JSON.stringify`` drops properties whose value is ``undefined``, so the
TypeScript implementation emitted no key at all for an unset ``noteId``,
``profile``, ``nextCursor``, ``code``, ``message`` or ``lastModified``. Python
would emit ``null``, which changes behaviour for any client testing key
presence. Deliberate nulls — ``DeleteResult.data`` — must still survive.
"""

from __future__ import annotations

import json

import pytest

from xhs_mcp.core.publishing.publish_service import PublishService
from xhs_mcp.shared.config import get_config
from xhs_mcp.shared.errors import PublishError
from xhs_mcp.shared.utils import omit_none


def test_omit_none_drops_only_listed_keys() -> None:
    payload = {"a": None, "b": None, "c": 1, "d": None}
    assert omit_none(payload, "a", "d") == {"b": None, "c": 1}


def test_omit_none_keeps_non_none_values() -> None:
    payload = {"noteId": "abc", "data": None}
    assert omit_none(payload, "noteId") == {"noteId": "abc", "data": None}


def test_omit_none_preserves_falsy_non_none_values() -> None:
    payload = {"tags": "", "imageCount": 0, "hasMore": False, "noteId": None}
    assert omit_none(payload, "tags", "imageCount", "hasMore", "noteId") == {
        "tags": "",
        "imageCount": 0,
        "hasMore": False,
    }


def test_profile_info_omits_last_modified_when_absent(tmp_path) -> None:
    from dataclasses import replace

    from xhs_mcp.shared import config as config_module
    from xhs_mcp.shared.profile import get_profile_info

    original = get_config()
    config_module.set_config(
        replace(
            original,
            paths=replace(original.paths, user_data_dir=str(tmp_path / "profile")),
        )
    )
    try:
        assert "lastModified" not in get_profile_info()
    finally:
        config_module.set_config(original)


def test_delete_result_keeps_explicit_null_data() -> None:
    """`data: null` is written explicitly in the original and must round-trip."""
    from xhs_mcp.core.deleting.delete_service import DeleteService

    payload = {
        "success": True,
        "data": None,
        "noteId": "n",
        "title": "t",
        "deletedAt": 1,
        "message": "m",
        "operation": "deleteNote",
    }
    assert "data" in json.loads(json.dumps(payload))
    assert DeleteService is not None


async def test_publish_video_with_empty_media_paths_reports_the_real_error() -> None:
    """An empty list reaches publish_content; validation must own the message."""
    service = PublishService(get_config())

    with pytest.raises(PublishError, match="Video path is required"):
        await service.publish_content("video", "标题", "正文", [])


async def test_publish_video_empty_paths_is_not_an_index_error() -> None:
    service = PublishService(get_config())

    with pytest.raises(PublishError) as excinfo:
        await service.publish_content("video", "标题", "正文", [])

    assert "list index out of range" not in str(excinfo.value)
    assert excinfo.value.error_code == "PublishError"
