"""Shared publishing behaviour for XHS MCP Server.

Filling the creator editor is defensive by necessity: XiaoHongShu ships UI
changes frequently, so each step walks a list of candidate selectors and falls
back progressively rather than relying on any single one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import ElementHandle, Page

from ...shared import js_snippets
from ...shared.base_service import BaseService
from ...shared.errors import PublishError
from ...shared.image_downloader import ImageDownloader
from ...shared.logger import logger
from ...shared.selectors import (
    COMMON_FILE_SELECTORS,
    COMMON_STATUS_SELECTORS,
    COMMON_TEXT_PATTERNS,
)
from ...shared.types import Config
from ...shared.utils import sleep
from ...shared.xhs_utils import is_element_in_viewport
from ..browser.browser_manager import BrowserManager

VIDEO_TIMEOUTS = {
    "PAGE_LOAD": 3000,
    "TAB_SWITCH": 2000,
    "VIDEO_PROCESSING": 10000,
    "CONTENT_WAIT": 1000,
    "UPLOAD_READY": 1000,
    "UPLOAD_START": 3000,
    "PROCESSING_CHECK": 3000,
    "COMPLETION_CHECK": 2000,
    "PROCESSING_TIMEOUT": 120000,  # 2 minutes
    "COMPLETION_TIMEOUT": 300000,  # 5 minutes
}

SELECTORS: dict[str, tuple[str, ...]] = {
    "FILE_INPUT": COMMON_FILE_SELECTORS["FILE_INPUT"],
    "SUCCESS_INDICATORS": COMMON_STATUS_SELECTORS["SUCCESS"],
    "ERROR_INDICATORS": COMMON_STATUS_SELECTORS["ERROR"],
    "PROCESSING_INDICATORS": COMMON_STATUS_SELECTORS["PROCESSING"],
    "COMPLETION_INDICATORS": (
        ".upload-complete",
        ".processing-complete",
        ".video-ready",
        '[class*="complete"]',
        '[class*="ready"]',
    ),
    "TOAST_SELECTORS": COMMON_STATUS_SELECTORS["TOAST"],
    "PUBLISH_PAGE_INDICATORS": (
        "div.upload-content",
        "div.submit",
        ".creator-editor",
        ".video-upload-container",
        'input[type="file"]',
    ),
}

TEXT_PATTERNS = COMMON_TEXT_PATTERNS

_TITLE_SELECTORS = (
    "input.c-input_inner",  # specific for recent Xiaohongshu creator UI
    "input.c-input",
    'input[placeholder*="标题"]',
    'input[placeholder*="填写标题会有更多赞哦"]',
    'input[placeholder*="title"]',
    'input[data-placeholder*="标题"]',
    ".title-input input",
    'input[placeholder*="请输入标题"]',
    'input[name="title"]',
    'input[id*="title"]',
    'input[class*="title"]',
    'input[type="text"]',  # Fallbacks
    'div[contenteditable="true"]',
    'textarea[placeholder*="标题"]',
    'textarea[placeholder*="title"]',
)

_CONTENT_SELECTORS = (
    ".tiptap.ProseMirror",
    'textarea[placeholder*="正文"]',
    "textarea[multiline]",
    'div[data-placeholder*="正文"]',
    ".content-editor",
    'div[role="textbox"]',
    'textbox[role="textbox"]',
    "textbox[multiline]",
)

_ANY_CONTENT_SELECTOR = (
    'div[role="textbox"][contenteditable="true"], .tiptap.ProseMirror, '
    'div[contenteditable="true"], textarea, [role="textbox"], .ql-editor, '
    'p[contenteditable="true"], textbox[multiline]'
)

_NOTE_ID_URL_RE = re.compile(r"/(?:explore|discovery)/([a-f0-9]+)", re.IGNORECASE)


class PublishBaseService(BaseService):
    """Common editor interaction shared by the image and video publishers."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        super().__init__(config, browser_manager)
        self.image_downloader = ImageDownloader("./temp_images")

    # ------------------------------------------------------------------
    # Element helpers
    # ------------------------------------------------------------------

    async def find_element_by_selectors(
        self, page: Page, selectors: tuple[str, ...] | list[str]
    ) -> ElementHandle | None:
        """Return the first element matching any of ``selectors``.

        Invalid selectors raise, exactly as ``querySelector`` does — see the note
        in :mod:`xhs_mcp.shared.selectors` about the ``:contains()`` entries.
        """
        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                logger.debug(f"Found element with selector: {selector}")
                return element
        return None

    async def get_element_text(self, element: ElementHandle) -> str | None:
        try:
            return await element.evaluate(js_snippets.GET_TEXT_CONTENT)
        except Exception as error:
            logger.warn(f"Failed to get element text: {error}")
            return None

    async def check_text_patterns(
        self, text: str | None, patterns: tuple[str, ...]
    ) -> bool:
        if not text:
            return False
        return any(pattern in text for pattern in patterns)

    async def check_element_for_patterns(
        self, page: Page, selectors: tuple[str, ...], patterns: tuple[str, ...]
    ) -> dict[str, Any]:
        """Find the first element whose text contains one of ``patterns``."""
        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                text = await self.get_element_text(element)
                if text and await self.check_text_patterns(text, patterns):
                    return {"found": True, "text": text, "element": element}
        return {"found": False}

    async def wait_for_condition(
        self,
        condition: Callable[[], Awaitable[bool]],
        timeout: int,
        check_interval: int = 1000,
        error_message: str = "",
    ) -> None:
        """Poll ``condition`` until it is true or ``timeout`` elapses."""
        import time

        start_time = time.time() * 1000

        while time.time() * 1000 - start_time < timeout:
            if await condition():
                return
            await sleep(check_interval)

        raise PublishError(error_message)

    async def is_element_visible(self, element: ElementHandle) -> bool:
        return await is_element_in_viewport(element)

    # ------------------------------------------------------------------
    # Title
    # ------------------------------------------------------------------

    async def fill_title(self, page: Page, title: str) -> None:
        """Locate the title input and type ``title`` into it."""
        try:
            await page.wait_for_selector(
                'input.c-input_inner, input.c-input, input[placeholder*="标题"], '
                '.title-input input, input[class*="title"]',
                timeout=10000,
            )
        except Exception:
            # Continue without waiting if not found purely by selector.
            pass

        for selector in _TITLE_SELECTORS:
            try:
                title_input = await page.query_selector(selector)
                if title_input:
                    # Scroll into view just in case it's off screen.
                    await page.evaluate(js_snippets.SCROLL_INTO_VIEW_SMOOTH, title_input)
                    await sleep(500)

                    if await is_element_in_viewport(title_input):
                        await title_input.click()
                        await sleep(500)  # Wait for focus

                        # Clear existing input if any.
                        await title_input.click(click_count=3)
                        await title_input.press("Backspace")

                        await title_input.type(title)
                        return
            except Exception:
                continue

        # Fall back to any visible non-file, non-hidden input or textarea.
        try:
            all_inputs = await page.query_selector_all("input, textarea")

            for input_element in all_inputs:
                try:
                    input_type = await page.evaluate(
                        js_snippets.GET_ATTRIBUTE, [input_element, "type"]
                    )

                    if input_type not in ("file", "hidden"):
                        await page.evaluate(
                            js_snippets.SCROLL_INTO_VIEW_SMOOTH, input_element
                        )
                        await sleep(500)

                        if await is_element_in_viewport(input_element):
                            await input_element.click()
                            await sleep(500)

                            await input_element.click(click_count=3)
                            await input_element.press("Backspace")

                            await input_element.type(title)
                            return
                except Exception:
                    continue
        except Exception:
            pass

        raise PublishError("Could not find title input field")

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    async def find_content_element(self, page: Page) -> ElementHandle | None:
        """Locate the rich-text body editor, trying the known editor shapes in turn."""
        try:
            # Strategy 1: plain contenteditable.
            content_editable = await page.query_selector('div[contenteditable="true"]')
            if content_editable and await is_element_in_viewport(content_editable):
                return content_editable

            # Strategy 2: tiptap/ProseMirror, the current creator platform editor.
            tiptap_editor = await page.query_selector("div.tiptap.ProseMirror")
            if tiptap_editor and await is_element_in_viewport(tiptap_editor):
                return tiptap_editor

            # Strategy 3: explicit textbox role.
            role_textbox = await page.query_selector(
                'div[role="textbox"][contenteditable="true"]'
            )
            if role_textbox and await is_element_in_viewport(role_textbox):
                return role_textbox

            # Strategy 4: legacy Quill editor.
            ql_editor = await page.query_selector("div.ql-editor")
            if ql_editor:
                return ql_editor

            # Strategy 5: any known content selector.
            for selector in _CONTENT_SELECTORS:
                element = await page.query_selector(selector)
                if element:
                    return element

            # Strategy 6: any visible multiline textbox.
            multiline_textboxes = await page.query_selector_all("textbox[multiline]")
            for element in multiline_textboxes:
                if await is_element_in_viewport(element):
                    return element

            return None
        except Exception:
            return None

    async def find_textbox_by_placeholder(self, page: Page) -> ElementHandle | None:
        try:
            p_elements = await page.query_selector_all("p")

            for p in p_elements:
                placeholder = await page.evaluate(
                    js_snippets.GET_ATTRIBUTE, [p, "data-placeholder"]
                )
                if placeholder and "输入正文描述" in placeholder:
                    return p

            return None
        except Exception:
            return None

    async def find_textbox_parent(self, page: Page, element: ElementHandle) -> Any:
        try:
            return await page.evaluate_handle(js_snippets.GET_PARENT_ELEMENT, element)
        except Exception:
            return None

    async def fill_content(self, page: Page, content: str) -> None:
        """Locate the body editor and type ``content`` into it."""
        try:
            await page.wait_for_selector(
                'div[role="textbox"][contenteditable="true"], .tiptap.ProseMirror, '
                'div[contenteditable="true"], textarea, [role="textbox"], .ql-editor, '
                "textbox[multiline]",
                timeout=10000,
            )
        except Exception:
            pass

        content_element = await self.find_content_element(page)

        if not content_element:
            textbox_element = await self.find_textbox_by_placeholder(page)
            if textbox_element:
                content_element = await self.find_textbox_parent(page, textbox_element)

        if not content_element:
            # Scan every plausible editor element and pick the first visible one.
            try:
                all_content_elements = await page.query_selector_all(_ANY_CONTENT_SELECTOR)

                for element in all_content_elements:
                    try:
                        is_visible = await is_element_in_viewport(element)
                        tag_name = await page.evaluate(js_snippets.GET_TAG_NAME, element)
                        content_editable = await page.evaluate(
                            js_snippets.GET_ATTRIBUTE, [element, "contenteditable"]
                        )
                        role = await page.evaluate(
                            js_snippets.GET_ATTRIBUTE, [element, "role"]
                        )
                        class_name = await page.evaluate(
                            js_snippets.GET_CLASS_NAME, element
                        )
                        multiline = await page.evaluate(
                            js_snippets.GET_ATTRIBUTE, [element, "multiline"]
                        )

                        if is_visible and (
                            content_editable == "true"
                            or tag_name == "TEXTAREA"
                            or role == "textbox"
                            or "ql-editor" in (class_name or "")
                            or "tiptap" in (class_name or "")
                            or multiline == ""
                        ):
                            content_element = element
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not content_element:
            # Last resort: scan the first 50 elements for anything content-shaped.
            try:
                all_elements = await page.query_selector_all("*")

                for element in all_elements[:50]:
                    try:
                        is_visible = await is_element_in_viewport(element)
                        tag_name = await page.evaluate(js_snippets.GET_TAG_NAME, element)
                        content_editable = await page.evaluate(
                            js_snippets.GET_ATTRIBUTE, [element, "contenteditable"]
                        )
                        class_name = await page.evaluate(
                            js_snippets.GET_CLASS_NAME, element
                        )
                        placeholder = await page.evaluate(
                            js_snippets.GET_ATTRIBUTE, [element, "placeholder"]
                        )

                        if is_visible and (
                            content_editable == "true"
                            or tag_name == "TEXTAREA"
                            or "content" in str(class_name or "")
                            or "editor" in str(class_name or "")
                            or "内容" in (placeholder or "")
                            or "正文" in (placeholder or "")
                        ):
                            content_element = element
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not content_element:
            raise PublishError("Could not find content input field")

        try:
            await content_element.click()
            await sleep(500)  # Wait for focus
            await content_element.type(content)
        except Exception as error:
            raise PublishError(f"Failed to fill content: {error}") from error

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    async def input_tags(self, page: Page, content_element: Any, tags: str) -> None:
        tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

        for tag in tag_list:
            await self.input_tag(page, content_element, tag)

    async def input_tag(self, page: Page, content_element: Any, tag: str) -> None:
        """Type ``#tag`` and confirm it via the topic suggestion list when present."""
        try:
            await content_element.type(f"#{tag}")
            await sleep(1000)

            topic_container = await page.query_selector("#creator-editor-topic-container")

            if topic_container:
                first_item = await topic_container.query_selector(".item")
                if first_item:
                    await first_item.click()
                    await sleep(500)
            else:
                # Confirm the tag, then separate it from the next one.
                await content_element.press("Enter")
                await sleep(500)
                await content_element.press("Space")
                await sleep(200)
        except Exception as error:
            logger.warn(f"Failed to add tag {tag}: {error}")

    async def add_tags(self, page: Page, tags: str) -> None:
        try:
            content_element = await self.find_content_element(page)
            if content_element:
                await self.input_tags(page, content_element, tags)
        except Exception as error:
            logger.warn(f"Failed to add tags: {error}")

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def _find_submit_button(self, page: Page) -> ElementHandle | None:
        """Locate the publish button across the several UI generations in the wild."""
        # Strategy 1: the <xhs-publish-btn> custom element (new XHS UI).
        custom_btn = await page.query_selector("xhs-publish-btn")
        if custom_btn:
            attrs = await custom_btn.evaluate(js_snippets.GET_PUBLISH_BTN_ATTRS)
            logger.debug(f"Found xhs-publish-btn custom element: {json.dumps(attrs)}")
            if attrs.get("isPublish") == "true" or attrs.get("submitText") == "发布":
                return custom_btn

        # Strategy 2: a standard <button> containing 发布.
        for btn in await page.query_selector_all("button"):
            text = await btn.evaluate(js_snippets.GET_TRIMMED_TEXT)
            if text and "发布" in text:
                return btn

        # Strategy 3: any short visible div/span containing 发布.
        for element in await page.query_selector_all("div, span"):
            try:
                text = await element.evaluate(js_snippets.GET_TRIMMED_TEXT)
                if text and "发布" in text and len(text) < 20:
                    if await is_element_in_viewport(element):
                        return element
            except Exception:
                continue

        # Strategy 4: known submit-button class names.
        submit_selector = (
            'div.submit, .submit-btn, .publish-btn, [class*="publish"], '
            '[class*="btn-"], .btn-text'
        )
        found = await page.query_selector(submit_selector)
        if found:
            return found

        # Strategy 5: XPath text match.
        for text_candidate in ("发布笔记", "发布", "发表"):
            elements = await page.query_selector_all(
                f"xpath=//*[contains(text(), '{text_candidate}')]"
            )
            for element in elements:
                try:
                    if await element.evaluate(js_snippets.HAS_NONZERO_BOUNDING_BOX):
                        return element
                except Exception:
                    continue

        # Strategy 6: a .btn-text span whose clickable ancestor is the real button.
        btn_text_el = await page.query_selector(".btn-text")
        if btn_text_el:
            text = await btn_text_el.evaluate(js_snippets.GET_TRIMMED_TEXT)
            if text and "发布" in text:
                parent = await btn_text_el.evaluate_handle(
                    js_snippets.CLOSEST_PUBLISH_PARENT
                )
                if parent:
                    return parent.as_element()

        return None

    async def submit_post(self, page: Page) -> None:
        """Click publish, escalating through several click strategies.

        XHS's button is a custom element wired to React handlers, so a plain
        click is not always enough; each strategy is followed by a check for
        whether publishing actually started.
        """
        try:
            submit_button = await self._find_submit_button(page)

            if not submit_button:
                debug_info = await page.evaluate(js_snippets.COLLECT_PUBLISH_DEBUG_INFO)
                raise PublishError(
                    f"Could not find submit button. URL={debug_info['url']}, "
                    f"body={debug_info['bodyHeight']}, vp={debug_info['viewportHeight']}, "
                    f"publishElems={json.dumps(debug_info['publishElements'], ensure_ascii=False)}"
                )

            button_state = await page.evaluate(
                js_snippets.GET_SUBMIT_BUTTON_STATE, submit_button
            )
            logger.debug(f"Submit button state: {json.dumps(button_state, ensure_ascii=False)}")

            if button_state.get("disabled"):
                logger.warn("Submit button is disabled - publishing may fail")

            await page.evaluate(js_snippets.SCROLL_INTO_VIEW_INSTANT, submit_button)
            await sleep(500)

            async def is_publish_triggered() -> bool:
                try:
                    current_url = page.url
                    body_text = await page.evaluate(js_snippets.GET_BODY_TEXT)
                    return (
                        "/publish/publish" not in current_url
                        or "发布成功" in body_text
                        or "审核中" in body_text
                    )
                except Exception:
                    return False

            # Strategy A: custom element listens for a CustomEvent('publish').
            is_custom_element = await submit_button.evaluate(
                js_snippets.IS_CUSTOM_PUBLISH_ELEMENT
            )
            if is_custom_element:
                try:
                    await page.evaluate(
                        js_snippets.DISPATCH_PUBLISH_CUSTOM_EVENT, submit_button
                    )
                    logger.debug('Dispatched CustomEvent("publish") on xhs-publish-btn')
                except Exception as custom_event_error:
                    logger.debug(f"CustomEvent dispatch failed: {custom_event_error}")
                await sleep(1500)
                if await is_publish_triggered():
                    return

            # Strategy B: full React-compatible mouse event chain.
            try:
                await page.evaluate(
                    js_snippets.DISPATCH_REACT_EVENT_CHAIN, submit_button
                )
                logger.debug("Dispatched full React event chain on submit button")
            except Exception as chain_error:
                logger.debug(f"React event chain failed: {chain_error}")
            await sleep(1000)
            if await is_publish_triggered():
                return

            # Strategy C: native Playwright click.
            try:
                await submit_button.click()
                logger.debug("Clicked submit button via Playwright native click")
            except Exception as click_error:
                logger.debug(f"Playwright click failed: {click_error}")
            await sleep(800)
            if await is_publish_triggered():
                return

            # Strategy D: element.click() from page context.
            try:
                await page.evaluate(js_snippets.CLICK_ELEMENT, submit_button)
                logger.debug("Clicked submit button via JS evaluate click")
            except Exception as js_click_error:
                logger.debug(f"JS evaluate click failed: {js_click_error}")
            await sleep(800)
            if await is_publish_triggered():
                return

            # Strategy E: synthesise a real mouse click at the element's centre.
            try:
                box = await submit_button.bounding_box()
                if box:
                    await page.mouse.move(
                        box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    )
                    await page.mouse.down()
                    await sleep(50)
                    await page.mouse.up()
                    logger.debug("Clicked submit button via mouse coordinates")
            except Exception as mouse_error:
                logger.debug(f"Mouse click failed: {mouse_error}")
            await sleep(1500)
        except PublishError:
            raise
        except Exception as error:
            raise PublishError(f"Failed to click submit button: {error}") from error

    # ------------------------------------------------------------------
    # Completion detection
    # ------------------------------------------------------------------

    async def wait_for_publish_completion(self, page: Page) -> str | None:
        """Poll for a publish result and return the new note id when detectable."""
        import time

        max_wait_time = 30000  # 30 seconds
        start_time = time.time() * 1000
        publish_start_url = page.url

        while time.time() * 1000 - start_time < max_wait_time:
            current_url = page.url

            # Strategy 1: explicit success indicators.
            for selector in (
                ".success-message",
                ".publish-success",
                '[data-testid="publish-success"]',
                ".toast-success",
            ):
                if await page.query_selector(selector):
                    logger.debug(f"Found success indicator: {selector}")
                    await sleep(2000)
                    return await self.extract_note_id_from_page(page)

            # Strategy 2: explicit error indicators.
            for selector in (
                ".error-message",
                ".publish-error",
                '[data-testid="publish-error"]',
                ".toast-error",
                ".error-toast",
            ):
                element = await page.query_selector(selector)
                if element:
                    error_text = await element.evaluate(js_snippets.GET_TEXT_CONTENT)
                    raise PublishError(f"Publish failed with error: {error_text}")

            # Strategy 3: are we still on the publish page at all?
            still_on_publish_page = False
            for selector in ("div.upload-content", "div.submit", ".creator-editor"):
                if await page.query_selector(selector):
                    still_on_publish_page = True
                    break

            if not still_on_publish_page:
                logger.debug("Left publish page, assuming success")
                return await self.extract_note_id_from_page(page)

            # Strategy 4: toast/popup text.
            for selector in (".toast", ".message", ".notification", '[role="alert"]'):
                element = await page.query_selector(selector)
                if element:
                    toast_text = await element.evaluate(js_snippets.GET_TEXT_CONTENT)
                    if toast_text:
                        if "成功" in toast_text or "success" in toast_text:
                            logger.debug(f"Found success toast: {toast_text}")
                            return await self.extract_note_id_from_page(page)
                        if (
                            "失败" in toast_text
                            or "error" in toast_text
                            or "错误" in toast_text
                        ):
                            raise PublishError(f"Publish failed: {toast_text}")

            # Strategy 5: broad text scan.
            for element in await page.query_selector_all("div, span, p, h1, h2, h3, button"):
                try:
                    text = await element.evaluate(js_snippets.GET_TRIMMED_TEXT)
                    if text and len(text) < 50:
                        if (
                            "发布成功" in text
                            or "投稿成功" in text
                            or "审核中" in text
                        ):
                            logger.debug(f"Found text success indicator: {text}")
                            return await self.extract_note_id_from_page(page)
                        if "发布失败" in text or "投稿失败" in text:
                            raise PublishError(f"Publish failed: {text}")
                except PublishError:
                    raise
                except Exception:
                    continue

            # Strategy 6: navigated away from the publish flow.
            if current_url != publish_start_url:
                is_publish_url = "/publish" in current_url or "/creator" in current_url
                if not is_publish_url:
                    logger.debug(
                        f"URL changed from publish page to {current_url}, assuming success"
                    )
                    return await self.extract_note_id_from_page(page)

            # Strategy 7: a visible success overlay.
            for selector in (
                ".modal",
                ".popup",
                ".dialog",
                ".overlay",
                '[class*="success"]',
                '[class*="modal"]',
            ):
                element = await page.query_selector(selector)
                if element:
                    try:
                        if await is_element_in_viewport(element):
                            text = await element.evaluate(js_snippets.GET_TRIMMED_TEXT)
                            if text and ("成功" in text or "发布" in text):
                                logger.debug(
                                    f"Found overlay with success text: {text[:50]}"
                                )
                                return await self.extract_note_id_from_page(page)
                    except Exception:
                        continue

            await sleep(800)

        # Timed out: gather enough context to tell success from failure.
        debug_info = await page.evaluate(js_snippets.COLLECT_COMPLETION_DEBUG_INFO)

        logger.debug(f"Publish timeout debug - URL: {debug_info['url']}")
        logger.debug(f"Visible texts: {' | '.join(debug_info['visibleTexts'])}")

        is_still_on_publish_url = "/publish" in debug_info["url"]
        has_error_text = any(
            ("失败" in t or "错误" in t or "error" in t or "无法" in t)
            for t in debug_info["visibleTexts"]
        )

        if not is_still_on_publish_url or not has_error_text:
            logger.warn(
                f"Publish completion timed out but no error detected. Assuming "
                f"success. URL={debug_info['url']}"
            )
            return await self.extract_note_id_from_page(page)

        raise PublishError(
            f"Publish completion timeout - could not determine result. "
            f"URL={debug_info['url']}, "
            f"texts={', '.join(debug_info['visibleTexts'])[:200]}"
        )

    async def extract_note_id_from_page(self, page: Page) -> str | None:
        """Find the id of the note that was just published."""
        try:
            # Method 1: the URL, if we were redirected to the note.
            current_url = page.url
            logger.debug(f"Current URL after publish: {current_url}")

            match = _NOTE_ID_URL_RE.search(current_url)
            if match:
                note_id = match.group(1)
                logger.debug(f"Extracted note ID from URL: {note_id}")
                return note_id

            # Method 2: data attributes, note links or a long hex string in the DOM.
            note_id_from_page = await page.evaluate(js_snippets.EXTRACT_NOTE_ID_FROM_PAGE)

            if note_id_from_page:
                logger.debug(f"Extracted note ID from page content: {note_id_from_page}")
                return note_id_from_page

            # Method 3: ask the creator centre for the most recent note.
            logger.debug("Could not extract note ID from page, trying fallback method")
            try:
                await sleep(5000)

                from ..notes.note_service import NoteService

                note_service = NoteService(self.get_config())
                user_notes = await note_service.get_user_notes(1)

                if user_notes.get("success") and user_notes.get("data"):
                    latest_note_id = user_notes["data"][0]["id"]
                    logger.debug(f"Extracted note ID from NoteService: {latest_note_id}")
                    return latest_note_id
            except Exception as error:
                logger.warn(f"Fallback note ID extraction failed: {error}")

            logger.debug("Could not extract note ID from any method")
            return None
        except Exception as error:
            logger.warn(f"Failed to extract note ID: {error}")
            return None
