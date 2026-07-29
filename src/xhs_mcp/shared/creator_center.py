"""Shared helpers for Creator Center page operations."""

from __future__ import annotations

from playwright.async_api import Page

from .errors import NotLoggedInError, XHSError
from .utils import sleep

CREATOR_CENTER_URL = "https://creator.xiaohongshu.com/new/note-manager?source=official"


async def navigate_to_creator_center(page: Page) -> None:
    try:
        await page.goto(CREATOR_CENTER_URL, wait_until="load", timeout=30000)
        await sleep(3000)
    except Exception as error:
        raise XHSError(
            "Failed to navigate to creator center",
            "CreatorCenterError",
            {"url": CREATOR_CENTER_URL},
            error,
        ) from error


async def verify_creator_auth(page: Page, login_ok_selector: str) -> None:
    """Confirm the session is authenticated on the Creator Center page.

    Falls back to looking for rendered notes, because the creator site does not
    always expose the same user chrome as the main site.
    """
    try:
        login_elements = await page.query_selector_all(login_ok_selector)
        creator_elements = await page.query_selector_all(
            '[class*="user"], [class*="profile"], [class*="avatar"]'
        )

        if not login_elements and not creator_elements:
            current_url = page.url
            if "login" in current_url or "signin" in current_url:
                raise NotLoggedInError("User not logged in", {"url": current_url})

            note_elements = await page.query_selector_all("div.note")
            if not note_elements:
                raise NotLoggedInError(
                    "User not logged in or no notes found", {"url": current_url}
                )
    except NotLoggedInError:
        raise
    except Exception as error:
        raise XHSError(
            "Failed to verify authentication",
            "CreatorCenterError",
            {"operation": "verifyAuth"},
            error,
        ) from error
