"""Video note publishing for XHS MCP Server."""

from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.async_api import Page

from ...shared import js_snippets
from ...shared.errors import PublishError
from ...shared.logger import logger
from ...shared.title_validator import assert_title_width_valid, get_title_width
from ...shared.types import PublishResult
from ...shared.utils import omit_none, sleep
from ...shared.xhs_utils import is_element_in_viewport
from .publish_base_service import SELECTORS, TEXT_PATTERNS, VIDEO_TIMEOUTS, PublishBaseService

_ALLOWED_VIDEO_EXTENSIONS = ("mp4", "mov", "avi", "mkv", "webm", "flv", "wmv")

_MAX_VIDEO_SIZE_MB = 500

_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:")

_VIDEO_TAB_SELECTORS = (
    "div.creator-tab",
    ".creator-tab",
    '[role="tab"]',
    ".tab",
    'div[class*="tab"]',
)


class VideoPublishService(PublishBaseService):
    """Publishes a single video note to the creator platform."""

    async def publish_video(
        self,
        title: str,
        content: str,
        video_path: str,
        tags: str = "",
        browser_path: str | None = None,
    ) -> PublishResult:
        self._validate_video_inputs(title, content, video_path)

        resolved_video_path = self._validate_and_resolve_video_path(video_path)

        try:
            page = await self.get_browser_manager().create_page(False, browser_path, True)

            try:
                note_id = await self._execute_video_publish_workflow(
                    page, title, content, resolved_video_path, tags
                )

                return omit_none(
                    {
                        "success": True,
                        "message": "Video published successfully",
                        "title": title,
                        "content": content,
                        "imageCount": 0,  # Videos don't have an image count.
                        "tags": tags,
                        "url": self.get_config().xhs.creator_video_publish_url,
                        "noteId": note_id or None,
                    },
                    "noteId",
                )
            finally:
                await page.close()
        except Exception as error:
            logger.error(f"Video publish error: {error}")
            raise

    @staticmethod
    def _validate_video_inputs(title: str, content: str, video_path: str) -> None:
        if not title or not title.strip():
            raise PublishError("Video title cannot be empty")

        assert_title_width_valid(title)
        logger.debug(
            f'Video title width validation passed: "{title}" '
            f"({get_title_width(title)} units)"
        )

        if not content or not content.strip():
            raise PublishError("Video content cannot be empty")

        if not video_path or not video_path.strip():
            raise PublishError("Video path is required")

    async def _execute_video_publish_workflow(
        self, page: Page, title: str, content: str, video_path: str, tags: str
    ) -> str | None:
        await self.get_browser_manager().navigate_with_retry(
            page, self.get_config().xhs.creator_video_publish_url
        )

        await sleep(VIDEO_TIMEOUTS["PAGE_LOAD"])

        await self._click_video_upload_tab(page)

        await sleep(VIDEO_TIMEOUTS["TAB_SWITCH"])

        await self._upload_video(page, video_path)

        # Videos take considerably longer to process than images.
        await sleep(VIDEO_TIMEOUTS["VIDEO_PROCESSING"])

        await self.fill_title(page, title)

        await sleep(VIDEO_TIMEOUTS["CONTENT_WAIT"])

        await self.fill_content(page, content)

        if tags:
            await self.add_tags(page, tags)

        await self.submit_post(page)

        return await self._wait_for_video_publish_completion(page)

    @staticmethod
    def _validate_and_resolve_video_path(video_path: str) -> str:
        resolved_path = (
            video_path
            if video_path.startswith("/") or _WINDOWS_DRIVE_RE.match(video_path)
            else os.path.join(os.getcwd(), video_path)
        )

        path_obj = Path(resolved_path)
        if not path_obj.exists():
            raise PublishError(f"Video file not found: {video_path}")

        if not path_obj.is_file():
            raise PublishError(f"Path is not a file: {video_path}")

        ext = video_path.lower().split(".")[-1] if "." in video_path else ""
        if not ext or ext not in _ALLOWED_VIDEO_EXTENSIONS:
            raise PublishError(
                f"Unsupported video format: {video_path}. "
                f"Supported: {', '.join(_ALLOWED_VIDEO_EXTENSIONS)}"
            )

        file_size_mb = path_obj.stat().st_size / (1024 * 1024)
        if file_size_mb > _MAX_VIDEO_SIZE_MB:
            raise PublishError(
                f"Video file too large: {file_size_mb:.2f}MB. "
                f"Maximum allowed: {_MAX_VIDEO_SIZE_MB}MB"
            )

        return resolved_path

    async def _click_video_upload_tab(self, page: Page) -> None:
        try:
            tabs: list = []
            for selector in _VIDEO_TAB_SELECTORS:
                found_tabs = await page.query_selector_all(selector)
                if found_tabs:
                    tabs = found_tabs
                    break

            if not tabs:
                logger.warn("No tabs found for video upload")
                return

            video_tab = None
            for tab in tabs:
                try:
                    if not await is_element_in_viewport(tab):
                        continue

                    text = await page.evaluate(js_snippets.GET_TEXT_CONTENT, tab)

                    if text and ("上传视频" in text or "视频" in text or "video" in text):
                        video_tab = tab
                        break
                except Exception:
                    continue

            if video_tab:
                await video_tab.click()
                await sleep(2000)
            else:
                # Fallback: the first visible tab is usually video upload.
                visible_tabs = [t for t in tabs if await is_element_in_viewport(t)]

                if visible_tabs:
                    await visible_tabs[0].click()
                    await sleep(2000)
        except Exception as error:
            logger.warn(f"Failed to click video upload tab: {error}")

    async def _upload_video(self, page: Page, video_path: str) -> None:
        logger.debug(f"Uploading video: {video_path}")

        file_input = await self.find_element_by_selectors(page, SELECTORS["FILE_INPUT"])
        if not file_input:
            raise PublishError("Could not find file upload input on video upload page")

        try:
            await sleep(VIDEO_TIMEOUTS["UPLOAD_READY"])

            await file_input.set_input_files(video_path)
            logger.debug("Video file uploaded, waiting for processing...")

            await sleep(VIDEO_TIMEOUTS["UPLOAD_START"])

            await self._wait_for_video_processing(page)
        except Exception as error:
            raise PublishError(f"Failed to upload video {video_path}: {error}") from error

    async def _wait_for_video_processing(self, page: Page) -> None:
        logger.debug("Waiting for video processing to complete...")

        try:

            async def condition() -> bool:
                complete_result = await self.check_element_for_patterns(
                    page, SELECTORS["COMPLETION_INDICATORS"], TEXT_PATTERNS["SUCCESS"]
                )

                if complete_result["found"]:
                    logger.debug(f"Video processing complete: {complete_result['text']}")
                    return True

                processing_result = await self.check_element_for_patterns(
                    page, SELECTORS["PROCESSING_INDICATORS"], TEXT_PATTERNS["PROCESSING"]
                )

                if processing_result["found"]:
                    logger.debug(f"Video processing: {processing_result['text']}")
                    return False  # Still processing, keep waiting.

                logger.debug(
                    "No processing indicators found, assuming video processing complete"
                )
                return True

            await self.wait_for_condition(
                condition,
                VIDEO_TIMEOUTS["PROCESSING_TIMEOUT"],
                VIDEO_TIMEOUTS["PROCESSING_CHECK"],
                "Video processing timeout",
            )
        except Exception:
            logger.warn("Video processing timeout, continuing anyway...")

    async def _wait_for_video_publish_completion(self, page: Page) -> str | None:
        logger.debug("Waiting for video publish completion...")

        async def condition() -> bool:
            success_result = await self.check_element_for_patterns(
                page, SELECTORS["SUCCESS_INDICATORS"], TEXT_PATTERNS["SUCCESS"]
            )

            if success_result["found"]:
                logger.debug(f"Found success indicator: {success_result['text']}")
                await sleep(VIDEO_TIMEOUTS["COMPLETION_CHECK"])
                return True

            error_result = await self.check_element_for_patterns(
                page, SELECTORS["ERROR_INDICATORS"], TEXT_PATTERNS["ERROR"]
            )

            if error_result["found"]:
                raise PublishError(
                    f"Video publish failed with error: {error_result['text']}"
                )

            still_on_page = await self.find_element_by_selectors(
                page, SELECTORS["PUBLISH_PAGE_INDICATORS"]
            )
            if not still_on_page:
                logger.debug("Left publish page, assuming video publish success")
                return True

            processing_result = await self.check_element_for_patterns(
                page, SELECTORS["PROCESSING_INDICATORS"], TEXT_PATTERNS["PROCESSING"]
            )

            if processing_result["found"]:
                logger.debug(f"Video still processing: {processing_result['text']}")

            toast_result = await self.check_element_for_patterns(
                page, SELECTORS["TOAST_SELECTORS"], TEXT_PATTERNS["SUCCESS"]
            )

            if toast_result["found"]:
                logger.debug(f"Found success toast: {toast_result['text']}")
                return True

            error_toast_result = await self.check_element_for_patterns(
                page, SELECTORS["TOAST_SELECTORS"], TEXT_PATTERNS["ERROR"]
            )

            if error_toast_result["found"]:
                raise PublishError(f"Video publish failed: {error_toast_result['text']}")

            return False

        # The check interval is fixed at call time in the original too: the
        # `isProcessing` flag it read was always still false at that point.
        await self.wait_for_condition(
            condition,
            VIDEO_TIMEOUTS["COMPLETION_TIMEOUT"],
            VIDEO_TIMEOUTS["COMPLETION_CHECK"],
            "Video publish completion timeout - could not determine result after 5 minutes",
        )

        return await self.extract_note_id_from_page(page)
