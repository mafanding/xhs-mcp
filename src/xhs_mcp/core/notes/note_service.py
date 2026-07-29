"""Note service for XHS MCP Server.

Handles the signed-in user's own notes, read from the Creator Center note
manager, plus deletion (delegated to :class:`DeleteService`).
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from ...shared import js_snippets
from ...shared.base_service import BaseService
from ...shared.creator_center import navigate_to_creator_center, verify_creator_auth
from ...shared.errors import NoteParsingError
from ...shared.logger import logger
from ...shared.types import Config, DeleteResult, UserNote, UserNotesResult
from ...shared.utils import omit_none
from ..browser.browser_manager import BrowserManager
from ..deleting.delete_service import DeleteService

NOTE_SELECTORS = {
    "NOTE_ELEMENTS": "div.note",
    "TITLE_ELEMENTS": '[class*="raw"], [class*="title"], [class*="name"]',
    "IMAGE_ELEMENTS": 'img[class*="media"], img[class*="cover"], img[class*="thumbnail"]',
    "STAT_ELEMENTS": '[class*="count"], [class*="stat"], [class*="number"]',
    "TAG_ELEMENTS": '[class*="tag"], [class*="label"]',
    "NOTE_LINK": 'a[href*="/explore/"], a[href*="/note/"]',
    "VISIBILITY_INDICATORS": (
        '[class*="private"], [class*="visibility"], [class*="lock"], '
        '[class*="eye"], [class*="public"], [class*="friends"], [class*="status"]'
    ),
    "PUBLISH_TIME": '[class*="time"], [class*="date"], [class*="publish-time"]',
}


class NoteService(BaseService):
    """Lists and deletes the current user's published notes."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        super().__init__(config, browser_manager)
        self.delete_service = DeleteService(config, self.browser_manager)

    async def get_user_notes(
        self,
        limit: int = 20,
        cursor: str | None = None,
        browser_path: str | None = None,
    ) -> UserNotesResult:
        """Return the current user's published notes from the Creator Center."""
        self._validate_get_user_notes_params(limit)

        page = await self.get_browser_manager().create_page(True, browser_path, True)

        try:
            await navigate_to_creator_center(page)
            await verify_creator_auth(page, self.get_config().xhs.login_ok_selector)

            notes_data = await self._extract_notes_from_creator_center(page)
            limited_notes = self._limit_notes(notes_data, limit)

            return omit_none(
                {
                    "success": True,
                    "data": limited_notes,
                    "total": len(notes_data),
                    "hasMore": len(notes_data) > limit,
                    "nextCursor": self._get_next_cursor(limited_notes),
                    "operation": "getUserNotes",
                },
                "nextCursor",
            )
        except Exception as error:
            logger.error(f"Failed to get user notes: {error}")
            return {
                "success": False,
                "data": [],
                "total": 0,
                "hasMore": False,
                "error": str(error),
                "operation": "getUserNotes",
            }
        finally:
            await page.close()

    @staticmethod
    def _validate_get_user_notes_params(limit: int) -> None:
        if limit <= 0:
            raise NoteParsingError("Limit must be greater than 0", {"limit": limit})
        if limit > 100:
            raise NoteParsingError("Limit cannot exceed 100", {"limit": limit})

    async def _extract_notes_from_creator_center(self, page: Page) -> list[dict[str, Any]]:
        try:
            return await page.evaluate(
                js_snippets.EXTRACT_NOTES_FROM_CREATOR_CENTER, NOTE_SELECTORS
            )
        except Exception as error:
            raise NoteParsingError(
                "Failed to extract notes from creator center",
                {"operation": "extractNotesFromCreatorCenter"},
                error,
            ) from error

    @staticmethod
    def _limit_notes(notes: list[dict[str, Any]], limit: int) -> list[UserNote]:
        return [
            {
                "id": note["id"],
                "title": note["title"],
                "content": note["content"],
                "images": list(note["images"]),
                "publishTime": note["publishTime"],
                "updateTime": note["updateTime"],
                "likeCount": note["likeCount"],
                "commentCount": note["commentCount"],
                "shareCount": note["shareCount"],
                "collectCount": note["collectCount"],
                "tags": list(note["tags"]),
                "url": note["url"],
                "visibility": note["visibility"],
                "visibilityText": note["visibilityText"],
            }
            for note in notes[:limit]
        ]

    @staticmethod
    def _get_next_cursor(notes: list[UserNote]) -> str | None:
        return notes[-1]["id"] if notes else None

    async def delete_note(
        self, note_id: str, browser_path: str | None = None
    ) -> DeleteResult:
        return await self.delete_service.delete_note(note_id, browser_path)

    async def delete_last_published_note(
        self, browser_path: str | None = None
    ) -> DeleteResult:
        return await self.delete_service.delete_last_published_note(browser_path)
