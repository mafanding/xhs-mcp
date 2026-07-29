"""Authentication service for XHS MCP Server."""

from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from ...shared import js_snippets
from ...shared.base_service import BaseService
from ...shared.cookies import delete_cookies_file
from ...shared.errors import LoginFailedError, LoginTimeoutError, XHSError
from ...shared.logger import logger
from ...shared.profile import clear_user_data_dir, is_profile_mode
from ...shared.types import Config, LoginResult, StatusResult
from ...shared.utils import omit_none, sleep
from ...shared.xhs_utils import get_login_status_with_profile, is_logged_in
from ..browser.browser_manager import BrowserManager

_USER_ID_RE = re.compile(r"/user/profile/([a-f0-9]+)")


class AuthService(BaseService):
    """Login, logout and login-status checks."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        super().__init__(config, browser_manager)

    async def _extract_profile_from_page(self, page: Page) -> dict[str, str] | None:
        """Pull the signed-in user's profile URL and id out of the page chrome."""
        try:
            profile_url = await page.evaluate(js_snippets.EXTRACT_PROFILE_URL)

            if profile_url:
                match = _USER_ID_RE.search(profile_url)
                if match:
                    return {"userId": match.group(1), "profileUrl": profile_url}
        except Exception as profile_error:
            logger.warn("Failed to get profile information:", profile_error)

        return None

    async def login(
        self, browser_path: str | None = None, timeout: int = 300
    ) -> LoginResult:
        """Open a headed browser and wait for the user to complete login.

        ``timeout`` is in seconds and is polled in 5-second slices, matching the
        original's behaviour of re-arming the selector wait.
        """
        try:
            page = await self.get_browser_manager().create_page(False, browser_path, True)

            try:
                await self.get_browser_manager().navigate_with_retry(
                    page, self.get_config().xhs.explore_url
                )

                if await is_logged_in(page):
                    profile: Any = None
                    try:
                        extracted = await self._extract_profile_from_page(page)
                        login_status = await get_login_status_with_profile(page)
                        profile = {**(extracted or {}), **(login_status.get("profile") or {})}
                    except Exception as profile_error:
                        logger.warn("Failed to get profile information:", profile_error)

                    return omit_none(
                        {
                            "success": True,
                            "message": "Already logged in",
                            "status": "logged_in",
                            "action": "none",
                            "profile": profile,
                        },
                        "profile",
                    )

                check_interval = 5
                max_checks = int(timeout / check_interval)

                for check_count in range(max_checks):
                    try:
                        await page.wait_for_selector(
                            self.get_config().xhs.login_ok_selector,
                            timeout=check_interval * 1000,
                        )
                        break
                    except PlaywrightTimeoutError:
                        elapsed = (check_count + 1) * check_interval

                        if check_count == max_checks - 1:
                            raise LoginTimeoutError(
                                f"Login timed out after {timeout} seconds. Please "
                                f"complete QR code scanning or manual login in the "
                                f"browser window.",
                                {
                                    "timeout": timeout,
                                    "url": self.get_config().xhs.explore_url,
                                    "elapsedTime": elapsed,
                                    "suggestion": (
                                        "Increase timeout parameter or complete login faster"
                                    ),
                                },
                            ) from None

                await self.get_browser_manager().save_cookies_from_page(page)

                await sleep(1000)
                login_status = await get_login_status_with_profile(page)
                if login_status.get("isLoggedIn"):
                    profile = login_status.get("profile")
                    try:
                        extracted = await self._extract_profile_from_page(page)
                        if extracted:
                            profile = {**(profile or {}), **extracted}
                    except Exception as profile_error:
                        logger.warn(
                            "Failed to get additional profile information:", profile_error
                        )

                    return omit_none(
                        {
                            "success": True,
                            "message": "Login successful",
                            "status": "logged_in",
                            "action": "logged_in",
                            "profile": profile,
                        },
                        "profile",
                    )

                raise LoginFailedError(
                    "Login process completed but authentication verification failed"
                )
            finally:
                await page.close()
        except (LoginTimeoutError, LoginFailedError):
            raise
        except Exception as error:
            logger.error(f"Login failed with unexpected error: {error}")
            raise XHSError(
                f"Login failed: {error}", "LoginError", {"timeout": timeout}, error
            ) from error

    async def logout(self) -> LoginResult:
        """Log out by deleting the stored cookie file (and browser profile).

        In profile mode the session also lives in the Chromium user data
        directory, so removing only ``cookies.json`` would leave the account
        signed in. The profile is deleted too, unless it lacks the marker file
        identifying it as ours — see :mod:`xhs_mcp.shared.profile`.
        """
        try:
            success = delete_cookies_file()
            profile_cleared, profile_error = clear_user_data_dir()

            if success:
                message = "Logged out successfully (cookies deleted)"
                if profile_cleared:
                    message = "Logged out successfully (cookies and browser profile deleted)"
                elif profile_error:
                    message = f"{message}, but the browser profile was kept: {profile_error}"

                return omit_none(
                    {
                        "success": True,
                        "message": message,
                        "status": "logged_out",
                        "action": "logged_out",
                        "profileCleared": profile_cleared if is_profile_mode() else None,
                    },
                    "profileCleared",
                )

            return {
                "success": False,
                "message": "Failed to delete cookies file",
                "status": "logged_out",
                "action": "none",
            }
        except Exception as error:
            logger.error(f"Logout failed: {error}")
            return {
                "success": False,
                "message": f"Logout failed: {error}",
                "status": "logged_out",
                "action": "none",
            }

    async def check_status(self, browser_path: str | None = None) -> StatusResult:
        """Check login status headlessly using the saved cookies."""
        try:
            page = await self.get_browser_manager().create_page(True, browser_path, True)

            try:
                await self.get_browser_manager().navigate_with_retry(
                    page, self.get_config().xhs.explore_url
                )
                await sleep(1000)

                logged_in = await is_logged_in(page)

                if not logged_in:
                    return {
                        "success": True,
                        "loggedIn": False,
                        "status": "logged_out",
                        "urlChecked": self.get_config().xhs.explore_url,
                    }

                profile = await self._extract_profile_from_page(page)

                return omit_none(
                    {
                        "success": True,
                        "loggedIn": True,
                        "status": "logged_in",
                        "urlChecked": self.get_config().xhs.explore_url,
                        "profile": profile,
                    },
                    "profile",
                )
            finally:
                await page.close()
        except Exception as error:
            logger.error(f"Status check failed: {error}")
            raise XHSError(
                f"Status check failed: {error}", "StatusCheckError", {}, error
            ) from error
