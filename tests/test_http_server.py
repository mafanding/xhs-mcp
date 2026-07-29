"""HTTP transport wiring.

Uses Starlette's test client, so no browser is launched.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from xhs_mcp.server.http_server import XHSHTTPMCPServer

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


@pytest.fixture
def client() -> TestClient:
    server = XHSHTTPMCPServer(port=0)
    with TestClient(server.app) as test_client:
        yield test_client


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "server": "xhs-mcp",
        "version": response.json()["version"],
        "transports": ["streamable-http", "sse"],
    }


def test_mcp_path_is_served_directly_without_redirect(client: TestClient) -> None:
    """Mounting would redirect /mcp -> /mcp/, which some MCP clients don't follow."""
    response = client.post(
        "/mcp",
        json=_INITIALIZE,
        headers={"Accept": "application/json, text/event-stream"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert "mcp-session-id" in response.headers


def test_initialize_returns_server_info(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=_INITIALIZE,
        headers={"Accept": "application/json, text/event-stream"},
    )

    assert '"serverInfo"' in response.text
    assert '"xhs-mcp"' in response.text


def test_cors_exposes_session_id_header(client: TestClient) -> None:
    response = client.post(
        "/mcp",
        json=_INITIALIZE,
        headers={
            "Accept": "application/json, text/event-stream",
            "Origin": "http://example.com",
        },
    )

    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-expose-headers"] == "Mcp-Session-Id"


def test_tools_list_over_streamable_http(client: TestClient) -> None:
    init = client.post(
        "/mcp",
        json=_INITIALIZE,
        headers={"Accept": "application/json, text/event-stream"},
    )
    session_id = init.headers["mcp-session-id"]
    headers = {
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": session_id,
    }

    client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=headers,
    )

    assert "xhs_publish_content" in response.text
    assert "xhs_auth_login" in response.text


def test_messages_path_is_served_directly_without_redirect(client: TestClient) -> None:
    # No SSE session exists, so this 4xx's - the point is that it is not a 307.
    response = client.post("/messages", json={}, follow_redirects=False)

    assert response.status_code != 307


def test_unknown_path_is_404(client: TestClient) -> None:
    assert client.get("/nope").status_code == 404
