"""HTTP Server with SSE and Streamable HTTP transport support.

Exposes the same tools and resources as the stdio server over three endpoints:

- ``/mcp``      — Streamable HTTP (protocol version 2025-03-26), all methods
- ``/sse`` + ``/messages`` — the deprecated HTTP+SSE transport (2024-11-05)
- ``/health``   — plain health check
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from ..shared.config import get_config
from ..shared.logger import logger
from .handlers.resource_handlers import ResourceHandlers
from .handlers.tool_handlers import ToolHandlers
from .mcp_server import create_mcp_server

_STARTUP_BANNER = """
==============================================
SUPPORTED TRANSPORT OPTIONS:

1. Streamable HTTP (Protocol version: 2025-03-26)
   Endpoint: /mcp
   Methods: GET, POST, DELETE
   Usage:
     - Initialize with POST to /mcp
     - Establish SSE stream with GET to /mcp
     - Send requests with POST to /mcp
     - Terminate session with DELETE to /mcp

2. HTTP + SSE (Protocol version: 2024-11-05)
   Endpoints: /sse (GET) and /messages (POST)
   Usage:
     - Establish SSE stream with GET to /sse
     - Send requests with POST to /messages?sessionId=<id>

3. Health Check
   Endpoint: /health
   Method: GET
   Usage: Check server status and supported transports
==============================================
"""


class _ASGIEndpoint:
    """Adapts a raw ASGI callable for use as a Starlette ``Route`` endpoint.

    Mounting these paths instead would make Starlette redirect ``/mcp`` to
    ``/mcp/``; the original server answers ``/mcp`` directly and some MCP
    clients do not follow redirects.
    """

    def __init__(self, handler: Any, label: str) -> None:
        self._handler = handler
        self._label = label

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger.info(f"Received {scope.get('method')} request to {self._label}")
        await self._handler(scope, receive, send)


class XHSHTTPMCPServer:
    """Starlette application hosting the MCP HTTP transports."""

    def __init__(self, port: int = 3000, host: str = "0.0.0.0") -> None:
        self.port = port
        self.host = host
        self.config = get_config()
        self.tool_handlers = ToolHandlers()
        self.resource_handlers = ResourceHandlers()

        self.server = create_mcp_server(self.tool_handlers, self.resource_handlers)

        # DNS-rebinding protection is off so the server stays reachable under
        # whatever Host/Origin a local MCP client sends, matching the original's
        # permissive CORS posture.
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

        self._session_manager = StreamableHTTPSessionManager(
            app=self.server, security_settings=security
        )
        self._sse_transport = SseServerTransport("/messages", security_settings=security)
        self._uvicorn_server: uvicorn.Server | None = None

        self.app = self._build_app()

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _build_app(self) -> Starlette:
        @contextlib.asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            async with self._session_manager.run():
                yield

        return Starlette(
            routes=[
                Route(
                    "/mcp",
                    endpoint=_ASGIEndpoint(self._session_manager.asgi_app, "/mcp"),
                ),
                Route("/sse", endpoint=self._handle_sse_connection, methods=["GET"]),
                Route(
                    "/messages",
                    endpoint=_ASGIEndpoint(
                        self._sse_transport.handle_post_message, "/messages"
                    ),
                ),
                Route("/health", endpoint=self._handle_health, methods=["GET"]),
            ],
            middleware=[
                Middleware(
                    CORSMiddleware,
                    # Allow all origins - adjust as needed for production.
                    allow_origins=["*"],
                    allow_methods=["*"],
                    allow_headers=["*"],
                    # Browser-based clients need to read the session id back.
                    expose_headers=["Mcp-Session-Id"],
                )
            ],
            lifespan=lifespan,
        )

    async def _handle_sse_connection(self, request: Request) -> Response:
        logger.info("Received GET request to /sse (deprecated SSE transport)")

        async with self._sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )

        return Response()

    async def _handle_health(self, _request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "server": self.config.server.name,
                "version": self.config.server.version,
                "transports": ["streamable-http", "sse"],
            }
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Serve until interrupted."""
        print(f"XHS MCP HTTP Server listening on port {self.port}")
        print(_STARTUP_BANNER)

        uvicorn_config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info" if logger.enabled else "warning",
        )
        self._uvicorn_server = uvicorn.Server(uvicorn_config)

        # uvicorn installs its own SIGINT/SIGTERM handlers and unwinds the
        # lifespan on shutdown, which closes the transports.
        await self._uvicorn_server.serve()

        logger.info("HTTP server shutdown complete")

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
