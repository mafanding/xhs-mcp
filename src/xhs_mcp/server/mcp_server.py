"""MCP Server for XiaoHongShu Operations (stdio transport)."""

from __future__ import annotations

from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from ..shared.config import get_config
from .handlers.resource_handlers import ResourceHandlers
from .handlers.tool_handlers import ToolHandlers
from .schemas.tool_schemas import XHS_RESOURCE_SCHEMAS, XHS_TOOL_SCHEMAS


def _to_tool_models() -> list[types.Tool]:
    return [
        types.Tool(
            name=schema["name"],
            description=schema["description"],
            input_schema=schema["inputSchema"],
        )
        for schema in XHS_TOOL_SCHEMAS
    ]


def _to_resource_models() -> list[types.Resource]:
    return [
        types.Resource(
            uri=schema["uri"],
            name=schema["name"],
            description=schema["description"],
            mime_type=schema["mimeType"],
        )
        for schema in XHS_RESOURCE_SCHEMAS
    ]


def _to_content_blocks(payload: dict[str, Any]) -> list[types.TextContent]:
    return [
        types.TextContent(type="text", text=block["text"])
        for block in payload.get("content", [])
    ]


def create_mcp_server(
    tool_handlers: ToolHandlers | None = None,
    resource_handlers: ResourceHandlers | None = None,
) -> Server:
    """Build a low-level MCP :class:`Server` wired to the XHS handlers.

    Shared by the stdio and HTTP entry points so both expose exactly the same
    tools, resources and payloads.
    """
    config = get_config()
    tools = tool_handlers or ToolHandlers()
    resources = resource_handlers or ResourceHandlers()

    async def on_list_tools(
        _context: Any, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=_to_tool_models())

    async def on_call_tool(
        _context: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # handle_tool_request already converts failures into a payload, so a
        # tool error is reported in-band rather than as a protocol error.
        result = await tools.handle_tool_request(params.name, params.arguments or {})
        return types.CallToolResult(content=_to_content_blocks(result))

    async def on_list_resources(
        _context: Any, _params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=_to_resource_models())

    async def on_read_resource(
        _context: Any, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        result = await resources.handle_resource_request(str(params.uri))
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=content["uri"],
                    mime_type=content["mimeType"],
                    text=content["text"],
                )
                for content in result["contents"]
            ]
        )

    return Server(
        name=config.server.name,
        version=config.server.version,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resources=on_list_resources,
        on_read_resource=on_read_resource,
    )


class XHSMCPServer:
    """Serves the XHS tools over stdio."""

    def __init__(self) -> None:
        self.config = get_config()
        self.tool_handlers = ToolHandlers()
        self.resource_handlers = ResourceHandlers()
        self.server = create_mcp_server(self.tool_handlers, self.resource_handlers)

    async def start(self) -> None:
        """Run until stdin closes.

        ``stdio_server()`` points fd 1 at stderr while serving, so stray writes
        from handlers or the browser subprocess cannot corrupt the JSON-RPC
        stream on stdout.
        """
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options(),
                )
        finally:
            # Hand the browser instance back so an owned browser is closed
            # rather than left behind for the OS to reap.
            await self.tool_handlers.shutdown()
