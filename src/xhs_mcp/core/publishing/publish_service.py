"""Unified publishing facade for XHS MCP Server."""

from __future__ import annotations

from ...shared.base_service import BaseService
from ...shared.types import Config, ContentType, PublishResult
from ..browser.browser_manager import BrowserManager
from .publish_image_service import ImagePublishService
from .publish_video_service import VideoPublishService


class PublishService(BaseService):
    """Routes publish requests to the image or video publisher."""

    def __init__(self, config: Config, browser_manager: BrowserManager | None = None) -> None:
        super().__init__(config, browser_manager)
        self.image_service = ImagePublishService(config, self.browser_manager)
        self.video_service = VideoPublishService(config, self.browser_manager)

    async def publish_note(
        self,
        title: str,
        content: str,
        image_paths: list[str],
        tags: str = "",
        browser_path: str | None = None,
    ) -> PublishResult:
        return await self.image_service.publish_note(
            title, content, image_paths, tags, browser_path
        )

    async def publish_video(
        self,
        title: str,
        content: str,
        video_path: str,
        tags: str = "",
        browser_path: str | None = None,
    ) -> PublishResult:
        return await self.video_service.publish_video(
            title, content, video_path, tags, browser_path
        )

    async def publish_content(
        self,
        content_type: ContentType,
        title: str,
        content: str,
        media_paths: list[str],
        tags: str = "",
        browser_path: str | None = None,
    ) -> PublishResult:
        if content_type == "image":
            return await self.publish_note(title, content, media_paths, tags, browser_path)

        # An empty list passes the caller's required-parameter check (it is
        # neither None nor ""), so indexing here would raise IndexError. JS read
        # `mediaPaths[0]` as undefined and let validation report the real
        # problem; pass "" so publish_video raises "Video path is required".
        video_path = media_paths[0] if media_paths else ""
        return await self.publish_video(
            title, content, video_path, tags, browser_path
        )
