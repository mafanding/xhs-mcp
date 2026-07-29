"""Tool and resource schemas for XHS MCP Server.

Kept as plain dicts so the CLI can print them and the MCP layer can convert
them to SDK models, and so the published JSON Schema stays identical to the
TypeScript server's.
"""

from __future__ import annotations

from typing import Any

XHS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "xhs_auth_login",
        "description": (
            "Start the XiaoHongShu login flow. Opens a browser for QR scanning "
            "and returns a taskId immediately; poll xhs_task_status or "
            "xhs_auth_status to see when it completes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
        },
    },
    {
        "name": "xhs_auth_logout",
        "description": "Logout from XiaoHongShu (clears saved cookies).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "xhs_auth_status",
        "description": "Check XiaoHongShu login status (fast check with browser).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
        },
    },
    {
        "name": "xhs_discover_feeds",
        "description": "Get home page feed list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
        },
    },
    {
        "name": "xhs_search_note",
        "description": "Search for notes by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (required)",
                },
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "xhs_get_note_detail",
        "description": "Get detailed information about a specific note.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "feed_id": {
                    "type": "string",
                    "description": "Feed ID (required)",
                },
                "xsec_token": {
                    "type": "string",
                    "description": "Security token for the feed (required)",
                },
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
            "required": ["feed_id", "xsec_token"],
        },
    },
    {
        "name": "xhs_comment_on_note",
        "description": "Comment on a note.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "feed_id": {
                    "type": "string",
                    "description": "Feed ID (required)",
                },
                "xsec_token": {
                    "type": "string",
                    "description": "Security token for the feed (required)",
                },
                "note": {
                    "type": "string",
                    "description": "Comment note (required)",
                },
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
            "required": ["feed_id", "xsec_token", "note"],
        },
    },
    {
        "name": "xhs_publish_content",
        "description": (
            "Publish content to XiaoHongShu (supports both images and videos). "
            "Runs as a background task: returns a taskId immediately, poll "
            "xhs_task_status for the result. Publishing takes minutes because "
            "the note body is typed with human-like timing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["image", "video"],
                    "description": (
                        'Content type: "image" for images, "video" for videos (required)'
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Content title (required, max 20 characters)",
                    "maxLength": 20,
                },
                "content": {
                    "type": "string",
                    "description": "Content description (required, max 1000 characters)",
                    "maxLength": 1000,
                },
                "media_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of media file paths (required, non-empty). For images: "
                        "1-18 image files. For videos: exactly 1 video file."
                    ),
                    "maxItems": 18,
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags (optional)",
                },
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
            "required": ["type", "title", "content", "media_paths"],
        },
    },
    {
        "name": "xhs_task_status",
        "description": (
            "Check a background task queued by xhs_publish_content or "
            "xhs_auth_login."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID returned when the work was queued (required)",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "xhs_task_list",
        "description": "List recent background tasks, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Number of tasks to return (default: 20)",
                },
                "kind": {
                    "type": "string",
                    "description": (
                        "Filter by task kind, e.g. publish_image, publish_video, "
                        "auth_login"
                    ),
                },
            },
        },
    },
    {
        "name": "xhs_get_user_notes",
        "description": "Get current user notes list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Number of notes to fetch (default: 20)",
                },
                "cursor": {
                    "type": "string",
                    "description": "Pagination cursor for next page",
                },
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
        },
    },
    {
        "name": "xhs_delete_note",
        "description": "Delete a user note by ID or delete the last published note.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": (
                        "Specific note ID to delete (optional if last_published is true)"
                    ),
                },
                "last_published": {
                    "type": "boolean",
                    "description": (
                        "Delete the last published note (optional if note_id is provided)"
                    ),
                },
                "browser_path": {
                    "type": "string",
                    "description": "Optional custom browser binary path",
                },
            },
        },
    },
]

XHS_RESOURCE_SCHEMAS: list[dict[str, Any]] = [
    {
        "uri": "xhs://cookies",
        "name": "XHS Authentication Cookies",
        "description": "Current XiaoHongShu authentication cookies and info",
        "mimeType": "application/json",
    },
    {
        "uri": "xhs://config",
        "name": "XHS Server Configuration",
        "description": "XHS MCP server configuration",
        "mimeType": "application/json",
    },
    {
        "uri": "xhs://status",
        "name": "XHS Server Status",
        "description": "Current server and authentication status",
        "mimeType": "application/json",
    },
]
