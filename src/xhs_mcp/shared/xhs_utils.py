"""Utility functions for XHS page interactions."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import ElementHandle, Page

from . import js_snippets
from .logger import logger
from .utils import sleep

XHS_HOME_URL = "https://www.xiaohongshu.com"
XHS_EXPLORE_URL = f"{XHS_HOME_URL}/explore"
XHS_SEARCH_URL = f"{XHS_HOME_URL}/search_result"
XHS_CREATOR_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"
LOGIN_OK_SELECTOR = ".main-container .user .link-wrapper .channel"


def make_search_url(keyword: str) -> str:
    params = urlencode({"keyword": keyword, "source": "web_explore_feed"})
    return f"{XHS_SEARCH_URL}?{params}"


def make_feed_detail_url(feed_id: str, xsec_token: str) -> str:
    params = urlencode({"xsec_token": xsec_token, "xsec_source": "pc_feed"})
    return f"{XHS_EXPLORE_URL}/{feed_id}?{params}"


async def is_element_in_viewport(element: ElementHandle) -> bool:
    """Playwright equivalent of Puppeteer's ``ElementHandle#isIntersectingViewport``.

    Deliberately *not* ``is_visible()``: that ignores scroll position and would
    report off-screen elements as visible, which would change which elements the
    publish flow decides to interact with.
    """
    try:
        return bool(await element.evaluate(js_snippets.IS_INTERSECTING_VIEWPORT))
    except Exception:
        return False


async def extract_initial_state(page: Page) -> dict[str, Any] | None:
    """Read the SPA's bootstrap state object out of the page."""
    try:
        # Puppeteer has no waitForLoadState here either; the original just settles.
        await sleep(1000)
    except Exception:
        pass

    try:
        result = await page.evaluate(js_snippets.EXTRACT_INITIAL_STATE)

        if not result:
            return None

        return json.loads(result)
    except Exception:
        return None


async def is_logged_in(page: Page) -> bool:
    try:
        elements = await page.query_selector_all(LOGIN_OK_SELECTOR)
        return len(elements) > 0
    except Exception:
        return False


async def get_login_status_with_profile(page: Page) -> dict[str, Any]:
    """Check login state and, when logged in, scrape whatever profile data is on screen."""
    try:
        elements = await page.query_selector_all(LOGIN_OK_SELECTOR)
        logged_in = len(elements) > 0

        if not logged_in:
            return {"isLoggedIn": False}

        profile_data: dict[str, Any] = {}
        try:
            profile_data = await page.evaluate(js_snippets.EXTRACT_LOGIN_PROFILE) or {}
        except Exception:
            logger.error("Error in page.evaluate")
            profile_data = {}

        return {
            "isLoggedIn": True,
            "profile": profile_data if profile_data else None,
        }
    except Exception:
        # If there's an error, fall back to a basic login check.
        try:
            elements = await page.query_selector_all(LOGIN_OK_SELECTOR)
            return {"isLoggedIn": len(elements) > 0}
        except Exception:
            return {"isLoggedIn": False}
