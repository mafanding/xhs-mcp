"""Tool request handlers for XHS MCP Server."""

from __future__ import annotations

from typing import Any

from ...core.auth.auth_service import AuthService
from ...core.browser.session_manager import get_session_manager
from ...core.feeds.feed_service import FeedService
from ...core.notes.note_service import NoteService
from ...core.publishing.publish_service import PublishService
from ...core.tasks import get_task_queue
from ...shared.config import get_config
from ...shared.errors import XHSError
from ...shared.title_validator import assert_title_width_valid
from ...shared.utils import (
    create_mcp_error_response,
    create_mcp_tool_response,
    validate_required_params,
)


class ToolHandlers:
    """Dispatches MCP tool calls to the domain services.

    This is the entry layer: it holds services and nothing else. Services reach
    the browser through the instance manager, which keeps every one of them on
    the same browser for a given profile — so there is no shared browser object
    to pass around here.

    One inherited consequence is worth knowing: the browser is launched on the
    first tool call and then reused, so whichever tool runs first fixes headless
    mode for the process lifetime.
    """

    def __init__(self) -> None:
        config = get_config()
        self.auth_service = AuthService(config)
        self.feed_service = FeedService(config)
        self.publish_service = PublishService(config)
        self.note_service = NoteService(config)

    async def shutdown(self) -> None:
        """Stop queued work and release the browser instances this process holds."""
        await get_task_queue().shutdown()
        await get_session_manager().shutdown_all()

    async def handle_auth_login(self, browser_path: str | None = None) -> dict[str, Any]:
        """Queue the login flow and return immediately.

        Login waits for a human to scan a QR code, so it cannot be answered
        inside a tool call; the caller polls ``xhs_task_status`` or
        ``xhs_auth_status``.
        """
        task = get_task_queue().submit(
            "auth_login",
            lambda: self.auth_service.login(browser_path),
            {"description": "Waiting for QR code login"},
        )

        return create_mcp_tool_response(
            {
                "success": True,
                "message": (
                    "Login process started. A browser window will open for you "
                    "to complete the login."
                ),
                "status": "login_started",
                "action": "browser_opened",
                "taskId": task.id,
                "instructions": [
                    "1. Complete the login process in the opened browser window",
                    "2. Scan QR code or enter your credentials",
                    "3. Login will be automatically verified and the session saved",
                    "4. Poll xhs_task_status with the taskId, or use xhs_auth_status",
                ],
                "note": (
                    "The login runs in the background. You can continue using "
                    "other tools while it completes."
                ),
            }
        )

    async def handle_auth_logout(self) -> dict[str, Any]:
        return create_mcp_tool_response(await self.auth_service.logout())

    async def handle_auth_status(self, browser_path: str | None = None) -> dict[str, Any]:
        return create_mcp_tool_response(await self.auth_service.check_status(browser_path))

    async def handle_discover_feeds(
        self, browser_path: str | None = None
    ) -> dict[str, Any]:
        return create_mcp_tool_response(await self.feed_service.get_feed_list(browser_path))

    async def handle_search_note(
        self, keyword: str | None = None, browser_path: str | None = None
    ) -> dict[str, Any]:
        validate_required_params({"keyword": keyword}, ["keyword"])
        return create_mcp_tool_response(
            await self.feed_service.search_feeds(keyword, browser_path)
        )

    async def handle_get_note_detail(
        self,
        feed_id: str | None = None,
        xsec_token: str | None = None,
        browser_path: str | None = None,
    ) -> dict[str, Any]:
        validate_required_params(
            {"feedId": feed_id, "xsecToken": xsec_token}, ["feedId", "xsecToken"]
        )
        return create_mcp_tool_response(
            await self.feed_service.get_feed_detail(feed_id, xsec_token, browser_path)
        )

    async def handle_comment_on_note(
        self,
        feed_id: str | None = None,
        xsec_token: str | None = None,
        note: str | None = None,
        browser_path: str | None = None,
    ) -> dict[str, Any]:
        validate_required_params(
            {"feedId": feed_id, "xsecToken": xsec_token, "note": note},
            ["feedId", "xsecToken", "note"],
        )
        return create_mcp_tool_response(
            await self.feed_service.comment_on_feed(
                feed_id, xsec_token, note, browser_path
            )
        )

    async def handle_publish_content(
        self,
        content_type: str | None = None,
        title: str | None = None,
        content: str | None = None,
        media_paths: list[str] | None = None,
        tags: str | None = None,
        browser_path: str | None = None,
    ) -> dict[str, Any]:
        validate_required_params(
            {
                "type": content_type,
                "title": title,
                "content": content,
                "mediaPaths": media_paths,
            },
            ["type", "title", "content", "mediaPaths"],
        )

        if content_type not in ("image", "video"):
            raise ValueError('Content type must be "image" or "video"')

        # Width-aware title validation (CJK counts double).
        assert_title_width_valid(title)
        if len(content) > 1000:
            raise ValueError("Content must be 1000 characters or less")

        # Publishing types the body one keystroke at a time with humanized
        # timing, so it runs for minutes. Queue it and hand back a task id
        # rather than holding the tool call open.
        task = get_task_queue().submit(
            f"publish_{content_type}",
            lambda: self.publish_service.publish_content(
                content_type, title, content, media_paths, tags or "", browser_path
            ),
            {"type": content_type, "title": title, "mediaCount": len(media_paths)},
        )

        return create_mcp_tool_response(
            {
                "success": True,
                "status": "queued",
                "taskId": task.id,
                "message": (
                    f"Publish queued as task {task.id}. Poll xhs_task_status with "
                    f"this taskId for the result."
                ),
                "queuePosition": get_task_queue().pending_count,
            }
        )

    async def handle_get_user_notes(
        self,
        limit: int | None = None,
        cursor: str | None = None,
        browser_path: str | None = None,
    ) -> dict[str, Any]:
        return create_mcp_tool_response(
            await self.note_service.get_user_notes(
                limit if limit is not None else 20, cursor, browser_path
            )
        )

    async def handle_delete_note(
        self,
        note_id: str | None = None,
        last_published: bool | None = None,
        browser_path: str | None = None,
    ) -> dict[str, Any]:
        if last_published:
            return create_mcp_tool_response(
                await self.note_service.delete_last_published_note(browser_path)
            )
        if note_id:
            return create_mcp_tool_response(
                await self.note_service.delete_note(note_id, browser_path)
            )
        raise ValueError("Either note_id or last_published must be specified")

    async def handle_task_status(self, task_id: str | None = None) -> dict[str, Any]:
        validate_required_params({"taskId": task_id}, ["taskId"])

        task = get_task_queue().get(task_id)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")

        return create_mcp_tool_response({"success": True, **task.to_dict()})

    async def handle_task_list(
        self, limit: int | None = None, kind: str | None = None
    ) -> dict[str, Any]:
        tasks = get_task_queue().list(limit if limit is not None else 20, kind)

        return create_mcp_tool_response(
            {
                "success": True,
                "tasks": [task.to_dict() for task in tasks],
                "count": len(tasks),
                "pending": get_task_queue().pending_count,
            }
        )

    async def handle_tool_request(
        self, name: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Route a tool call, converting errors into MCP payloads rather than raising."""
        args = args or {}

        try:
            if name == "xhs_auth_login":
                return await self.handle_auth_login(args.get("browser_path"))

            if name == "xhs_auth_logout":
                return await self.handle_auth_logout()

            if name == "xhs_auth_status":
                return await self.handle_auth_status(args.get("browser_path"))

            if name == "xhs_discover_feeds":
                return await self.handle_discover_feeds(args.get("browser_path"))

            if name == "xhs_search_note":
                return await self.handle_search_note(
                    args.get("keyword"), args.get("browser_path")
                )

            if name == "xhs_get_note_detail":
                return await self.handle_get_note_detail(
                    args.get("feed_id"),
                    args.get("xsec_token"),
                    args.get("browser_path"),
                )

            if name == "xhs_comment_on_note":
                return await self.handle_comment_on_note(
                    args.get("feed_id"),
                    args.get("xsec_token"),
                    args.get("note"),
                    args.get("browser_path"),
                )

            if name == "xhs_publish_content":
                return await self.handle_publish_content(
                    args.get("type"),
                    args.get("title"),
                    args.get("content"),
                    args.get("media_paths"),
                    args.get("tags"),
                    args.get("browser_path"),
                )

            if name == "xhs_get_user_notes":
                return await self.handle_get_user_notes(
                    args.get("limit"), args.get("cursor"), args.get("browser_path")
                )

            if name == "xhs_task_status":
                return await self.handle_task_status(args.get("task_id"))

            if name == "xhs_task_list":
                return await self.handle_task_list(args.get("limit"), args.get("kind"))

            if name == "xhs_delete_note":
                return await self.handle_delete_note(
                    args.get("note_id"),
                    args.get("last_published"),
                    args.get("browser_path"),
                )

            raise ValueError(f"Unknown tool: {name}")
        except XHSError as error:
            return create_mcp_tool_response(error.to_dict())
        except Exception as error:
            return create_mcp_error_response(error)
