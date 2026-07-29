"""Tool request handlers for XHS MCP Server."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ...core.auth.auth_service import AuthService
from ...core.browser.browser_manager import BrowserManager
from ...core.feeds.feed_service import FeedService
from ...core.notes.note_service import NoteService
from ...core.publishing.publish_service import PublishService
from ...shared.config import get_config
from ...shared.errors import XHSError
from ...shared.logger import logger
from ...shared.title_validator import assert_title_width_valid
from ...shared.utils import (
    create_mcp_error_response,
    create_mcp_tool_response,
    safe_error_handler,
    validate_required_params,
)


class ToolHandlers:
    """Dispatches MCP tool calls to the domain services.

    All services share one :class:`BrowserManager`, matching the original. Note
    the consequence: the browser is launched on the first tool call and cached,
    so whichever tool runs first fixes headless mode for the process lifetime.
    """

    def __init__(self) -> None:
        config = get_config()
        self.browser_manager = BrowserManager(config)
        self.auth_service = AuthService(config, self.browser_manager)
        self.feed_service = FeedService(config, self.browser_manager)
        self.publish_service = PublishService(config, self.browser_manager)
        self.note_service = NoteService(config, self.browser_manager)
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def handle_auth_login(self, browser_path: str | None = None) -> dict[str, Any]:
        """Kick off login in the background and return immediately.

        Login needs a human to scan a QR code, so blocking the tool call would
        stall the client for minutes; the caller polls ``xhs_auth_status``.
        """

        async def run_login() -> None:
            try:
                await self.auth_service.login(browser_path)
            except Exception as error:
                safe_error_handler(error, "Background login error", logger)

        task = asyncio.create_task(run_login())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "success": True,
                            "message": (
                                "Login process started. A browser window will open "
                                "for you to complete the login."
                            ),
                            "status": "login_started",
                            "action": "browser_opened",
                            "instructions": [
                                "1. Complete the login process in the opened browser window",
                                "2. Scan QR code or enter your credentials",
                                "3. Login will be automatically verified and cookies saved",
                                "4. Use xhs_auth_status to check if login completed",
                            ],
                            "note": (
                                "The login process runs in the background. You can "
                                "continue using other tools while login completes."
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                }
            ]
        }

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

        return create_mcp_tool_response(
            await self.publish_service.publish_content(
                content_type, title, content, media_paths, tags or "", browser_path
            )
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
