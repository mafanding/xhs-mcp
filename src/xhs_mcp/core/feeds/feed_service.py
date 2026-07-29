"""Feed operations service for XHS MCP Server."""

from __future__ import annotations

import json

from ...shared import js_snippets
from ...shared.base_service import BaseService
from ...shared.errors import (
    FeedError,
    FeedNotFoundError,
    FeedParsingError,
    NotLoggedInError,
    XHSError,
)
from ...shared.logger import logger
from ...shared.types import (
    CommentResult,
    Config,
    FeedDetailResult,
    FeedListResult,
    SearchResult,
)
from ...shared.utils import sleep
from ...shared.xhs_utils import (
    extract_initial_state,
    is_logged_in,
    make_feed_detail_url,
    make_search_url,
)
from ..browser.browser_manager import BrowserManager


class FeedService(BaseService):
    """Home feed discovery, search, note detail and commenting."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        super().__init__(config, browser_manager)

    async def get_feed_list(self, browser_path: str | None = None) -> FeedListResult:
        """Read the home page recommendation feed out of the SPA state."""
        try:
            page = await self.get_browser_manager().create_page(True, browser_path, True)

            try:
                await self.get_browser_manager().navigate_with_retry(
                    page, self.get_config().xhs.home_url
                )
                await sleep(1000)

                if not await is_logged_in(page):
                    raise NotLoggedInError(
                        "Must be logged in to access feed list",
                        {"operation": "get_feed_list"},
                    )

                # The feed hydrates asynchronously, so poll the state object.
                feed_data: str | None = None
                max_attempts = 10

                for attempt in range(1, max_attempts + 1):
                    await sleep(2000)

                    feed_data = await page.evaluate(js_snippets.EXTRACT_HOME_FEEDS)

                    if feed_data:
                        logger.info(f"Feed results loaded after {attempt} attempts")
                        break

                if not feed_data:
                    raise FeedParsingError(
                        f"Could not extract feed data after {max_attempts} attempts. "
                        f"The page may not be fully loaded or the state structure has "
                        f"changed.",
                        {
                            "url": self.get_config().xhs.home_url,
                            "suggestion": "Try logging in first using xhs_auth_login tool",
                        },
                    )

                feeds_value = json.loads(feed_data)

                return {
                    "success": True,
                    "feeds": feeds_value,
                    "count": len(feeds_value),
                    "source": "home_page",
                    "url": self.get_config().xhs.home_url,
                }
            finally:
                await page.close()
        except (NotLoggedInError, FeedParsingError):
            raise
        except Exception as error:
            logger.error(f"Failed to get feed list: {error}")
            raise XHSError(
                f"Failed to get feed list: {error}", "GetFeedListError", {}, error
            ) from error

    async def search_feeds(
        self, keyword: str, browser_path: str | None = None
    ) -> SearchResult:
        """Search notes by keyword."""
        if not keyword or not keyword.strip():
            raise FeedError("Search keyword cannot be empty")

        trimmed_keyword = keyword.strip()

        try:
            page = await self.get_browser_manager().create_page(True, browser_path, True)

            try:
                search_url = make_search_url(trimmed_keyword)
                await self.get_browser_manager().navigate_with_retry(page, search_url)

                search_data: str | None = None
                max_attempts = 10

                for attempt in range(1, max_attempts + 1):
                    await sleep(2000)

                    search_data = await page.evaluate(js_snippets.EXTRACT_SEARCH_FEEDS)

                    if search_data:
                        logger.info(f"Search results loaded after {attempt} attempts")
                        break

                if not search_data:
                    raise FeedParsingError(
                        f"Could not extract search results for keyword: "
                        f"{trimmed_keyword} after {max_attempts} attempts",
                        {"keyword": trimmed_keyword, "url": search_url},
                    )

                feeds_value = json.loads(search_data)

                return {
                    "success": True,
                    "keyword": trimmed_keyword,
                    "feeds": feeds_value,
                    "count": len(feeds_value),
                    "searchUrl": search_url,
                }
            finally:
                await page.close()
        except FeedError:
            raise
        except Exception as error:
            logger.error(f"Feed search failed for keyword '{trimmed_keyword}': {error}")
            raise XHSError(
                f"Feed search failed: {error}",
                "SearchFeedsError",
                {"keyword": trimmed_keyword},
                error,
            ) from error

    async def get_feed_detail(
        self, feed_id: str, xsec_token: str, browser_path: str | None = None
    ) -> FeedDetailResult:
        """Fetch the full detail record for a single note."""
        if not feed_id or not xsec_token:
            raise FeedError("Both feed_id and xsec_token are required")

        try:
            page = await self.get_browser_manager().create_page(True, browser_path, True)

            try:
                detail_url = make_feed_detail_url(feed_id, xsec_token)
                await self.get_browser_manager().navigate_with_retry(page, detail_url)
                await sleep(1000)

                state = await extract_initial_state(page)

                note_data = (state or {}).get("note")
                if not state or not note_data or not note_data.get("noteDetailMap"):
                    raise FeedParsingError(
                        f"Could not extract note details for feed: {feed_id}",
                        {"feedId": feed_id, "url": detail_url},
                    )

                note_detail_map = note_data["noteDetailMap"]
                if feed_id not in note_detail_map:
                    raise FeedNotFoundError(
                        f"Feed {feed_id} not found in note details",
                        {
                            "feedId": feed_id,
                            "availableFeeds": list(note_detail_map.keys()),
                        },
                    )

                return {
                    "success": True,
                    "feedId": feed_id,
                    "detail": note_detail_map[feed_id],
                    "url": detail_url,
                }
            finally:
                await page.close()
        except FeedError:
            # Covers FeedNotFoundError and FeedParsingError, which subclass FeedError.
            raise
        except Exception as error:
            logger.error(f"Failed to get feed detail for {feed_id}: {error}")
            raise XHSError(
                f"Failed to get feed detail: {error}",
                "GetFeedDetailError",
                {"feedId": feed_id},
                error,
            ) from error

    async def comment_on_feed(
        self,
        feed_id: str,
        xsec_token: str,
        note: str,
        browser_path: str | None = None,
    ) -> CommentResult:
        """Post a comment on a note."""
        if not feed_id or not xsec_token or not note:
            raise FeedError("feed_id, xsec_token, and note are all required")

        if len(note.strip()) == 0:
            raise FeedError("Comment note cannot be empty")

        try:
            page = await self.get_browser_manager().create_page(False, browser_path, True)

            try:
                detail_url = make_feed_detail_url(feed_id, xsec_token)
                await self.get_browser_manager().navigate_with_retry(page, detail_url)
                await sleep(1000)

                if not await is_logged_in(page):
                    raise NotLoggedInError(
                        "Must be logged in to comment on feeds",
                        {"operation": "comment_on_feed", "feedId": feed_id},
                    )

                comment_input_selector = "div.input-box div.content-edit span"
                if not await self.get_browser_manager().try_wait_for_selector(
                    page, comment_input_selector
                ):
                    raise FeedError(
                        "Comment input not found on page",
                        {"feedId": feed_id, "selector": comment_input_selector},
                    )

                comment_input = await page.query_selector(comment_input_selector)
                if comment_input:
                    await comment_input.click()

                editor_selector = "div.input-box div.content-edit p.content-input"
                editor = await page.query_selector(editor_selector)

                if editor:
                    await editor.click()
                    await editor.type(note, delay=30)
                await sleep(1000)

                submit_selector = "div.bottom button.submit"
                submit_button = await page.query_selector(submit_selector)
                if submit_button:
                    await submit_button.click()
                await sleep(2000)

                return {
                    "success": True,
                    "message": "Comment submitted successfully",
                    "feedId": feed_id,
                    "note": note,
                    "url": detail_url,
                }
            finally:
                await page.close()
        except (FeedError, NotLoggedInError):
            raise
        except Exception as error:
            logger.error(f"Failed to comment on feed {feed_id}: {error}")
            raise XHSError(
                f"Failed to comment on feed: {error}",
                "CommentOnFeedError",
                {"feedId": feed_id},
                error,
            ) from error
