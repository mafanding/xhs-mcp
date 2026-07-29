"""Delete service for XHS MCP Server.

Note deletion happens in the Creator Center note manager, whose markup differs
between account types and rollout cohorts — hence the broad selector lists and
the "direct delete button, else more-options dropdown" two-step.
"""

from __future__ import annotations

import time
from typing import Any

from playwright.async_api import Page

from ...shared import js_snippets
from ...shared.base_service import BaseService
from ...shared.creator_center import navigate_to_creator_center, verify_creator_auth
from ...shared.errors import DeleteError
from ...shared.logger import logger
from ...shared.selectors import COMMON_BUTTON_SELECTORS, COMMON_MODAL_SELECTORS
from ...shared.types import Config, DeleteResult
from ...shared.utils import sleep
from ..browser.browser_manager import BrowserManager

DELETE_SELECTORS: dict[str, tuple[str, ...]] = {
    "NOTE_ITEM": (
        "div.note",
        ".note-item",
        '[class*="note"]',
        "[data-impression]",
        ".creator-note-item",
        ".note-card",
        ".content-item",
    ),
    "DELETE_BUTTON": (
        ".control.data-del",
        "span.control.data-del",
        *COMMON_BUTTON_SELECTORS["DELETE"],
    ),
    "CONFIRM_BUTTON": COMMON_BUTTON_SELECTORS["CONFIRM"],
    "CANCEL_BUTTON": COMMON_BUTTON_SELECTORS["CANCEL"],
    "MORE_OPTIONS": COMMON_BUTTON_SELECTORS["MORE_OPTIONS"],
    "DROPDOWN_MENU": COMMON_MODAL_SELECTORS["DROPDOWN_MENU"],
    "MODAL_CONFIRM": COMMON_MODAL_SELECTORS["CONFIRM"],
    "MODAL_CANCEL": COMMON_MODAL_SELECTORS["CANCEL"],
}

# page.evaluate() serialises its argument as JSON, so hand the browser plain lists.
_JS_DELETE_SELECTORS = {key: list(value) for key, value in DELETE_SELECTORS.items()}


def _now_ms() -> int:
    return int(time.time() * 1000)


class DeleteService(BaseService):
    """Deletes notes by id, or the most recently published note."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        super().__init__(config, browser_manager)

    async def delete_note(
        self, note_id: str, browser_path: str | None = None
    ) -> DeleteResult:
        """Delete the note with the given id."""
        self._validate_delete_params(note_id)

        page = await self.get_browser_manager().create_page(True, browser_path, True)

        try:
            await navigate_to_creator_center(page)
            await verify_creator_auth(page, self.get_config().xhs.login_ok_selector)

            result = await self._find_and_delete_note(page, note_id)

            return {
                "success": True,
                "data": None,
                "noteId": result["noteId"],
                "title": result["title"],
                "deletedAt": _now_ms(),
                "message": (
                    f'Successfully deleted note "{result["title"]}" '
                    f'(ID: {result["noteId"]})'
                ),
                "operation": "deleteNote",
            }
        except Exception as error:
            logger.error(f"Failed to delete note {note_id}: {error}")
            return {
                "success": False,
                "data": None,
                "error": str(error),
                "message": f"Failed to delete note: {error}",
                "deletedAt": _now_ms(),
                "operation": "deleteNote",
            }
        finally:
            await page.close()

    async def delete_last_published_note(
        self, browser_path: str | None = None
    ) -> DeleteResult:
        """Delete the most recently published note."""
        page = await self.get_browser_manager().create_page(True, browser_path, True)

        try:
            await navigate_to_creator_center(page)
            await verify_creator_auth(page, self.get_config().xhs.login_ok_selector)

            result = await self._find_and_delete_last_note(page)

            return {
                "success": True,
                "data": None,
                "noteId": result["noteId"],
                "title": result["title"],
                "deletedAt": _now_ms(),
                "message": (
                    f'Successfully deleted last published note "{result["title"]}" '
                    f'(ID: {result["noteId"]})'
                ),
                "operation": "deleteLastPublishedNote",
            }
        except Exception as error:
            logger.error(f"Failed to delete last published note: {error}")
            return {
                "success": False,
                "data": None,
                "error": str(error),
                "message": f"Failed to delete last published note: {error}",
                "deletedAt": _now_ms(),
                "operation": "deleteLastPublishedNote",
            }
        finally:
            await page.close()

    @staticmethod
    def _validate_delete_params(note_id: str) -> None:
        if not note_id or len(note_id.strip()) == 0:
            raise DeleteError("Note ID is required", {"noteId": note_id})

    async def _find_and_delete_note(self, page: Page, note_id: str) -> dict[str, Any]:
        try:
            result = await page.evaluate(
                js_snippets.FIND_AND_CLICK_DELETE_FOR_NOTE,
                [_JS_DELETE_SELECTORS, note_id],
            )

            if not result["found"]:
                raise DeleteError(
                    result.get("error") or "Note not found", {"noteId": note_id}
                )

            if result.get("needsDropdown"):
                await self._click_delete_in_dropdown(page, {"noteId": note_id})

            await sleep(1000)
            await self._handle_confirmation_dialog(page)

            return {"noteId": result["noteId"], "title": result["title"]}
        except Exception as error:
            raise DeleteError(
                "Failed to find and delete note", {"noteId": note_id}, error
            ) from error

    async def _find_and_delete_last_note(self, page: Page) -> dict[str, Any]:
        try:
            result = await page.evaluate(
                js_snippets.FIND_AND_CLICK_DELETE_FOR_LAST_NOTE, _JS_DELETE_SELECTORS
            )

            if not result["found"]:
                raise DeleteError(result.get("error") or "Failed to find delete button", {})

            if result.get("needsDropdown"):
                await self._click_delete_in_dropdown(page, {})

            # Wait for the confirmation dialog if one appears.
            await sleep(1000)

            await self._handle_confirmation_dialog(page)

            return {"noteId": result["noteId"], "title": result["title"]}
        except Exception as error:
            raise DeleteError("Failed to find and delete last note", {}, error) from error

    async def _click_delete_in_dropdown(
        self, page: Page, context: dict[str, Any]
    ) -> None:
        """After a more-options click, find the delete entry inside the dropdown."""
        await sleep(1000)
        clicked = False

        for selector in DELETE_SELECTORS["DROPDOWN_MENU"]:
            dropdown = await page.query_selector(selector)
            if dropdown:
                for delete_selector in DELETE_SELECTORS["DELETE_BUTTON"]:
                    delete_btn = await dropdown.query_selector(delete_selector)
                    if delete_btn:
                        await delete_btn.click()
                        clicked = True
                        break
                if clicked:
                    break

        if not clicked:
            raise DeleteError("Delete button not found in dropdown menu", context)

    async def _handle_confirmation_dialog(self, page: Page) -> None:
        """Confirm the delete when a dialog appears; some flows delete immediately."""
        try:
            await sleep(2000)

            confirm_button = None

            for selector in DELETE_SELECTORS["CONFIRM_BUTTON"]:
                confirm_button = await page.query_selector(selector)
                if confirm_button:
                    logger.info(f"Found confirm button with selector: {selector}")
                    break

            if not confirm_button:
                for selector in DELETE_SELECTORS["MODAL_CONFIRM"]:
                    confirm_button = await page.query_selector(selector)
                    if confirm_button:
                        logger.info(
                            f"Found modal confirm button with selector: {selector}"
                        )
                        break

            if confirm_button:
                logger.info("Clicking confirmation button")
                await confirm_button.click()
                await sleep(2000)
            else:
                logger.info("No confirmation dialog found, delete might be immediate")
        except Exception as error:
            logger.warn(f"Failed to handle confirmation dialog: {error}")
            # Continue anyway as the delete might still have worked.
