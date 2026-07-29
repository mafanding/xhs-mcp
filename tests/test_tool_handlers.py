"""Tool dispatch, validation and MCP payload shapes.

Every service call is stubbed, so these exercise routing and error handling
without launching a browser.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from xhs_mcp.server.handlers.tool_handlers import ToolHandlers
from xhs_mcp.server.schemas.tool_schemas import XHS_RESOURCE_SCHEMAS, XHS_TOOL_SCHEMAS
from xhs_mcp.shared.errors import FeedParsingError


class _Recorder:
    """Stands in for a service, recording the call and returning a fixed payload."""

    def __init__(self, result: Any = None) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.result = result if result is not None else {"success": True}

    def __getattr__(self, name: str) -> Any:
        async def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result

        return call


@pytest.fixture
def handlers() -> ToolHandlers:
    instance = ToolHandlers.__new__(ToolHandlers)
    instance.auth_service = _Recorder()  # type: ignore[assignment]
    instance.feed_service = _Recorder()  # type: ignore[assignment]
    instance.publish_service = _Recorder()  # type: ignore[assignment]
    instance.note_service = _Recorder()  # type: ignore[assignment]
    return instance


def _payload(response: dict[str, Any]) -> Any:
    return json.loads(response["content"][0]["text"])


def test_every_schema_tool_is_routable() -> None:
    """Guard against a tool being declared but not dispatched."""
    source = (
        __import__(
            "xhs_mcp.server.handlers.tool_handlers", fromlist=["x"]
        ).__file__
    )
    with open(source) as handle:
        text = handle.read()

    for schema in XHS_TOOL_SCHEMAS:
        assert f'"{schema["name"]}"' in text, schema["name"]


def test_schema_counts() -> None:
    assert len(XHS_TOOL_SCHEMAS) == 12
    assert len(XHS_RESOURCE_SCHEMAS) == 3


async def test_unknown_tool_returns_error_payload(handlers: ToolHandlers) -> None:
    payload = _payload(await handlers.handle_tool_request("nope"))
    assert payload == {
        "success": False,
        "error": "UnknownError",
        "message": "Unknown tool: nope",
    }


async def test_missing_required_parameter(handlers: ToolHandlers) -> None:
    payload = _payload(await handlers.handle_tool_request("xhs_search_note", {}))
    assert payload["success"] is False
    assert payload["message"] == "Missing required parameters: keyword"


async def test_xhs_error_is_serialised_with_its_family_code(
    handlers: ToolHandlers,
) -> None:
    handlers.feed_service = _Recorder(FeedParsingError("bad state", {"url": "u"}))  # type: ignore[assignment]

    payload = _payload(
        await handlers.handle_tool_request("xhs_discover_feeds", {})
    )

    assert payload == {
        "success": False,
        "error": "FeedError",
        "message": "bad state",
        "context": {"url": "u"},
    }


async def test_search_note_routes_keyword_and_browser_path(
    handlers: ToolHandlers,
) -> None:
    await handlers.handle_tool_request(
        "xhs_search_note", {"keyword": "美食", "browser_path": "/x"}
    )
    assert handlers.feed_service.calls == [("search_feeds", ("美食", "/x"), {})]  # type: ignore[attr-defined]


async def test_get_note_detail_requires_both_ids(handlers: ToolHandlers) -> None:
    payload = _payload(
        await handlers.handle_tool_request("xhs_get_note_detail", {"feed_id": "a"})
    )
    assert payload["message"] == "Missing required parameters: xsecToken"


async def test_comment_routes_all_arguments(handlers: ToolHandlers) -> None:
    await handlers.handle_tool_request(
        "xhs_comment_on_note",
        {"feed_id": "f", "xsec_token": "t", "note": "hi"},
    )
    assert handlers.feed_service.calls == [  # type: ignore[attr-defined]
        ("comment_on_feed", ("f", "t", "hi", None), {})
    ]


async def test_publish_rejects_unknown_type(handlers: ToolHandlers) -> None:
    payload = _payload(
        await handlers.handle_tool_request(
            "xhs_publish_content",
            {"type": "audio", "title": "t", "content": "c", "media_paths": ["a.jpg"]},
        )
    )
    assert payload["message"] == 'Content type must be "image" or "video"'


async def test_publish_rejects_over_wide_title(handlers: ToolHandlers) -> None:
    payload = _payload(
        await handlers.handle_tool_request(
            "xhs_publish_content",
            {
                "type": "image",
                "title": "中" * 25,
                "content": "c",
                "media_paths": ["a.jpg"],
            },
        )
    )
    assert payload["error"] == "PublishError"
    assert "Title width exceeds limit: 50 units" in payload["message"]


async def test_publish_rejects_over_long_content(handlers: ToolHandlers) -> None:
    payload = _payload(
        await handlers.handle_tool_request(
            "xhs_publish_content",
            {
                "type": "image",
                "title": "ok",
                "content": "x" * 1001,
                "media_paths": ["a.jpg"],
            },
        )
    )
    assert payload["message"] == "Content must be 1000 characters or less"


async def test_publish_is_queued_and_returns_a_task_id(handlers: ToolHandlers) -> None:
    """Publishing runs for minutes, so it must not hold the tool call open."""
    from xhs_mcp.core.tasks import get_task_queue

    payload = _payload(
        await handlers.handle_tool_request(
            "xhs_publish_content",
            {
                "type": "image",
                "title": "标题",
                "content": "正文",
                "media_paths": ["a.jpg"],
                "tags": "a,b",
            },
        )
    )

    assert payload["status"] == "queued"
    assert payload["taskId"]

    task = await get_task_queue().wait(payload["taskId"], timeout=5)
    assert task.status.value == "succeeded"
    assert handlers.publish_service.calls == [  # type: ignore[attr-defined]
        ("publish_content", ("image", "标题", "正文", ["a.jpg"], "a,b", None), {})
    ]


async def test_get_user_notes_defaults_limit_to_20(handlers: ToolHandlers) -> None:
    await handlers.handle_tool_request("xhs_get_user_notes", {})
    assert handlers.note_service.calls == [("get_user_notes", (20, None, None), {})]  # type: ignore[attr-defined]


async def test_delete_note_prefers_last_published(handlers: ToolHandlers) -> None:
    await handlers.handle_tool_request(
        "xhs_delete_note", {"note_id": "abc", "last_published": True}
    )
    assert handlers.note_service.calls[0][0] == "delete_last_published_note"  # type: ignore[attr-defined]


async def test_delete_note_by_id(handlers: ToolHandlers) -> None:
    await handlers.handle_tool_request("xhs_delete_note", {"note_id": "abc"})
    assert handlers.note_service.calls == [("delete_note", ("abc", None), {})]  # type: ignore[attr-defined]


async def test_delete_note_requires_a_target(handlers: ToolHandlers) -> None:
    payload = _payload(await handlers.handle_tool_request("xhs_delete_note", {}))
    assert payload["message"] == "Either note_id or last_published must be specified"


async def test_logout_routes(handlers: ToolHandlers) -> None:
    await handlers.handle_tool_request("xhs_auth_logout")
    assert handlers.auth_service.calls == [("logout", (), {})]  # type: ignore[attr-defined]


async def test_login_returns_immediately_with_a_task_id(
    handlers: ToolHandlers,
) -> None:
    """Login needs a human at the browser, so the tool must not block on it."""
    payload = _payload(await handlers.handle_tool_request("xhs_auth_login", {}))

    assert payload["status"] == "login_started"
    assert payload["action"] == "browser_opened"
    assert len(payload["instructions"]) == 4
    assert payload["taskId"]


async def test_tool_response_is_pretty_printed_json(handlers: ToolHandlers) -> None:
    handlers.auth_service = _Recorder({"success": True, "status": "logged_out"})  # type: ignore[assignment]
    response = await handlers.handle_tool_request("xhs_auth_logout")

    assert response["content"][0]["type"] == "text"
    assert response["content"][0]["text"].startswith("{\n")


async def test_non_ascii_is_not_escaped(handlers: ToolHandlers) -> None:
    handlers.auth_service = _Recorder({"success": True, "message": "已登出"})  # type: ignore[assignment]
    response = await handlers.handle_tool_request("xhs_auth_logout")
    assert "已登出" in response["content"][0]["text"]
