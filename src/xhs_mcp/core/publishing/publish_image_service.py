"""Image note publishing for XHS MCP Server."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.async_api import Page

from ...shared import js_snippets
from ...shared.errors import InvalidImageError, PublishError
from ...shared.logger import logger
from ...shared.title_validator import assert_title_width_valid, get_title_width
from ...shared.types import PublishResult
from ...shared.utils import omit_none, sleep
from ...shared.xhs_utils import is_element_in_viewport
from .publish_base_service import PublishBaseService

_ALLOWED_IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "gif", "webp", "bmp")

_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:")

_IMAGE_PUBLISH_URL = (
    "https://creator.xiaohongshu.com/publish/publish?source=official&from=menu&target=image"
)

_ALTERNATIVE_UPLOAD_SELECTORS = (
    "div.upload-content",
    ".upload-content",
    'div[class*="upload"]',
    'div[class*="image"]',
    'input[type="file"]',
)


class ImagePublishService(PublishBaseService):
    """Publishes image notes (1-18 images) to the creator platform."""

    async def publish_note(
        self,
        title: str,
        content: str,
        image_paths: list[str],
        tags: str = "",
        browser_path: str | None = None,
    ) -> PublishResult:
        if not title or not title.strip():
            raise PublishError("Note title cannot be empty")

        # CJK characters count as 2 width units, ASCII as 1.
        assert_title_width_valid(title)
        logger.debug(
            f'Title width validation passed: "{title}" ({get_title_width(title)} units)'
        )

        if not content or not content.strip():
            raise PublishError("Note content cannot be empty")

        if not image_paths:
            raise PublishError("At least one image is required")

        resolved_paths = await self._validate_and_resolve_image_paths(image_paths)

        upload_selector = "div.upload-content"

        try:
            page = await self.get_browser_manager().create_page(False, browser_path, True)

            try:
                await self.get_browser_manager().navigate_with_retry(
                    page, self.get_config().xhs.creator_publish_url
                )

                await sleep(2000)

                await self._click_upload_tab(page)

                await sleep(2000)

                has_upload_container = await self.get_browser_manager().try_wait_for_selector(
                    page, upload_selector, 30000
                )

                if not has_upload_container:
                    for selector in _ALTERNATIVE_UPLOAD_SELECTORS:
                        has_upload_container = (
                            await self.get_browser_manager().try_wait_for_selector(
                                page, selector, 10000
                            )
                        )
                        if has_upload_container:
                            break

                if not has_upload_container:
                    raise PublishError("Could not find upload container on publish page")

                await self._upload_images(page, resolved_paths)

                # Large files need time to upload and transcode on XHS's side.
                logger.debug("Waiting 10 seconds for images to be uploaded and processed...")
                await sleep(10000)

                # Wait for the page to switch into edit mode.
                try:
                    await page.wait_for_selector(
                        'input[placeholder*="标题"], div[contenteditable="true"], '
                        ".tiptap.ProseMirror",
                        timeout=15000,
                    )
                except Exception:
                    pass

                await sleep(1000)

                await self.fill_title(page, title)

                await sleep(1000)

                await self.fill_content(page, content)

                if tags:
                    await self.add_tags(page, tags)

                await self.submit_post(page)

                note_id = await self.wait_for_publish_completion(page)

                return omit_none(
                    {
                        "success": True,
                        "message": "Note published successfully",
                        "title": title,
                        "content": content,
                        "imageCount": len(resolved_paths),
                        "tags": tags,
                        "url": self.get_config().xhs.creator_publish_url,
                        "noteId": note_id or None,
                    },
                    "noteId",
                )
            finally:
                await page.close()
        except Exception as error:
            logger.error(f"Publish error: {error}")
            raise

    async def _validate_and_resolve_image_paths(self, image_paths: list[str]) -> list[str]:
        """Download any URLs and check every resulting local file."""
        resolved_paths = await self.image_downloader.process_image_paths(image_paths)

        for resolved_path in resolved_paths:
            # Relative paths resolve against the process working directory, as
            # they did in the original.
            full_path = (
                resolved_path
                if resolved_path.startswith("/") or _WINDOWS_DRIVE_RE.match(resolved_path)
                else os.path.join(os.getcwd(), resolved_path)
            )

            path_obj = Path(full_path)
            if not path_obj.exists():
                raise InvalidImageError(f"Image file not found: {resolved_path}")

            if not path_obj.is_file():
                raise InvalidImageError(f"Path is not a file: {resolved_path}")

            ext = resolved_path.lower().split(".")[-1] if "." in resolved_path else ""
            if not ext or ext not in _ALLOWED_IMAGE_EXTENSIONS:
                raise InvalidImageError(
                    f"Unsupported image format: {resolved_path}. "
                    f"Supported: {', '.join(_ALLOWED_IMAGE_EXTENSIONS)}"
                )

        if len(resolved_paths) > 18:
            raise PublishError("Maximum 18 images allowed")

        return resolved_paths

    async def _click_upload_tab(self, page: Page) -> None:
        """Make sure the editor is on the image tab rather than the video tab."""
        try:
            logger.debug('Attempting to switch to "上传图文" tab')

            # Strategy 1: navigate straight to the image publish URL.
            await page.goto(_IMAGE_PUBLISH_URL, wait_until="networkidle", timeout=30000)
            logger.debug(f"Navigated directly to image publish URL: {_IMAGE_PUBLISH_URL}")
            await sleep(2000)

            page_state = await page.evaluate(js_snippets.GET_UPLOAD_PAGE_STATE)
            logger.debug(
                f"Page state after navigation: {json.dumps(page_state, ensure_ascii=False)}"
            )

            if not page_state["hasImageUpload"] and page_state["hasVideoUpload"]:
                logger.warn("Still on video upload page after navigation. Trying tab click...")

                # Strategy 2: click the image tab explicitly.
                tabs = await page.query_selector_all(
                    'div[class*="tab"], .creator-tab, [role="tab"]'
                )
                for tab in tabs:
                    text = await tab.evaluate(js_snippets.GET_TRIMMED_TEXT)
                    if text and ("上传图文" in text or "图文" in text):
                        if not await is_element_in_viewport(tab):
                            continue

                        # React needs the full event chain, not just a click.
                        await tab.evaluate(js_snippets.DISPATCH_TAB_EVENT_CHAIN)
                        await sleep(500)

                        await tab.click()
                        logger.debug("Clicked image tab via Playwright")
                        await sleep(1000)
                        break

            await sleep(1000)
        except Exception as error:
            logger.warn(f"Failed to switch to image tab: {error}")

    async def _upload_images(self, page: Page, image_paths: list[str]) -> None:
        try:
            logger.debug("Uploading images using direct input element targeting")

            file_input = await page.query_selector('input[type="file"]')
            if not file_input:
                raise PublishError("Could not find file upload input on page")

            # Allow multiple files of any type so the frontend can't block the set.
            await page.evaluate(js_snippets.PREPARE_FILE_INPUT, file_input)

            logger.debug(
                f"Submitting {len(image_paths)} image paths to file input element"
            )
            await file_input.set_input_files(image_paths)

            # Dispatch change manually in case the framework missed it.
            await page.evaluate(js_snippets.DISPATCH_CHANGE_EVENT, file_input)

            await sleep(8000)
        except Exception as error:
            raise PublishError(f"Failed to upload images: {error}") from error
