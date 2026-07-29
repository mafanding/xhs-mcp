"""Resource request handlers for XHS MCP Server."""

from __future__ import annotations

import json
from typing import Any

from ...core.auth.auth_service import AuthService
from ...shared.config import config_to_json_dict, get_config
from ...shared.profile import get_profile_info

_FRAMEWORK = "MCP Python"


class ResourceHandlers:
    """Serves the ``xhs://cookies``, ``xhs://config`` and ``xhs://status`` resources."""

    def __init__(self) -> None:
        self.auth_service = AuthService(get_config())

    async def get_cookies_resource(self) -> str:
        """Describe where the session lives.

        The session is a persistent Chromium profile rather than a cookie file,
        so this reports the profile directory and the cookie count read from it.
        """
        try:
            return json.dumps(get_profile_info(), ensure_ascii=False, indent=2)
        except Exception as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False, indent=2)

    async def get_config_resource(self) -> str:
        try:
            config = get_config()
            config_dict = config_to_json_dict(config)
            config_dict["framework"] = _FRAMEWORK
            config_dict["version"] = config.server.version
            return json.dumps(config_dict, ensure_ascii=False, indent=2)
        except Exception as error:
            return json.dumps({"error": str(error)}, ensure_ascii=False, indent=2)

    async def get_status_resource(self) -> str:
        try:
            # A status check is best-effort here: a failure must not break the resource.
            auth_status: Any
            try:
                auth_status = await self.auth_service.check_status()
            except Exception as error:
                auth_status = {"status": "error", "error": str(error)}

            profile_info = get_profile_info()
            config = get_config()

            status_data = {
                "server": {
                    "status": "running",
                    "name": config.server.name,
                    "version": config.server.version,
                    "framework": _FRAMEWORK,
                },
                "authentication": auth_status,
                "cookies": {
                    "profileExists": profile_info["profileExists"],
                    "cookieCount": profile_info["cookieCount"],
                },
                "capabilities": {
                    "toolsAvailable": 8,
                    "promptsAvailable": 0,
                    "resourcesAvailable": 3,
                },
            }

            return json.dumps(status_data, ensure_ascii=False, indent=2)
        except Exception as error:
            return json.dumps(
                {
                    "server": {"status": "error", "error": str(error)},
                    "framework": _FRAMEWORK,
                },
                ensure_ascii=False,
                indent=2,
            )

    async def handle_resource_request(self, uri: str) -> dict[str, Any]:
        try:
            if uri == "xhs://cookies":
                content = await self.get_cookies_resource()
            elif uri == "xhs://config":
                content = await self.get_config_resource()
            elif uri == "xhs://status":
                content = await self.get_status_resource()
            else:
                raise ValueError(f"Unknown resource: {uri}")

            return {
                "contents": [
                    {"uri": uri, "mimeType": "application/json", "text": content}
                ]
            }
        except Exception as error:
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(
                            {"error": str(error)}, ensure_ascii=False, indent=2
                        ),
                    }
                ]
            }
