"""Image downloader for XHS MCP Server.

Downloads images from HTTP/HTTPS URLs into a local cache directory so they can
be handed to the browser's file input. Filenames are derived from a hash of the
URL, which makes the cache stable across runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlparse

import httpx

from .errors import InvalidImageError
from .logger import logger

_EXTENSION_RE = re.compile(r"\.(jpg|jpeg|png|gif|webp|bmp)$", re.IGNORECASE)

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


class DownloadResult(TypedDict):
    originalUrl: str
    localPath: str
    cached: bool
    fileSize: int


class ImageDownloader:
    """Downloads and caches remote images, and validates local image paths."""

    def __init__(
        self,
        save_dir: str = "./temp_images",
        timeout: int = 30000,
        max_file_size: int = 10 * 1024 * 1024,
    ) -> None:
        self.save_dir = save_dir
        self.timeout = timeout
        self.max_file_size = max_file_size

        Path(self.save_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def is_image_url(path: str) -> bool:
        """Return True when ``path`` is an HTTP(S) URL rather than a local path."""
        if not path:
            return False
        lower = path.lower().strip()
        return lower.startswith("http://") or lower.startswith("https://")

    def _generate_file_name(self, image_url: str) -> str:
        """Derive a stable cache filename from the URL hash.

        No timestamp: the name must be reproducible so a repeated URL hits the
        cache instead of downloading again.
        """
        short_hash = hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:16]

        extension = "jpg"
        try:
            pathname = urlparse(image_url).path.lower()
            match = _EXTENSION_RE.search(pathname)
            if match:
                extension = match.group(1)
        except ValueError:
            pass

        return f"img_{short_hash}.{extension}"

    @staticmethod
    def _validate_image_data(buffer: bytes) -> tuple[bool, str]:
        """Identify the image type from its magic number."""
        if len(buffer) < 12:
            return False, ""

        if buffer[0:3] == b"\xff\xd8\xff":
            return True, "jpg"

        if buffer[0:4] == b"\x89PNG":
            return True, "png"

        if buffer[0:3] == b"GIF":
            return True, "gif"

        if buffer[0:4] == b"RIFF" and buffer[8:12] == b"WEBP":
            return True, "webp"

        if buffer[0:2] == b"BM":
            return True, "bmp"

        return False, ""

    async def download_image(self, image_url: str) -> DownloadResult:
        """Download a single image, returning the cached copy when present."""
        if not self.is_image_url(image_url):
            raise InvalidImageError(
                f"Invalid image URL format: {image_url}",
                {
                    "url": image_url,
                    "suggestion": "URL must start with http:// or https://",
                },
            )

        file_name = self._generate_file_name(image_url)
        local_path = Path(self.save_dir) / file_name

        if local_path.exists():
            logger.debug(f"Using cached image: {local_path}")
            return {
                "originalUrl": image_url,
                "localPath": str(local_path),
                "cached": True,
                "fileSize": local_path.stat().st_size,
            }

        logger.debug(f"Downloading image from: {image_url}")

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout / 1000, follow_redirects=True
            ) as client:
                response = await client.get(image_url, headers={"User-Agent": _USER_AGENT})

                if response.status_code >= 400:
                    raise InvalidImageError(
                        f"Failed to download image: HTTP {response.status_code} "
                        f"{response.reason_phrase}",
                        {
                            "url": image_url,
                            "statusCode": response.status_code,
                            "statusText": response.reason_phrase,
                        },
                    )

                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_file_size:
                    size_mb = int(content_length) / 1024 / 1024
                    max_mb = self.max_file_size / 1024 / 1024
                    raise InvalidImageError(
                        f"Image file too large: {size_mb:.2f}MB (max: {max_mb:.2f}MB)",
                        {
                            "url": image_url,
                            "fileSize": int(content_length),
                            "maxSize": self.max_file_size,
                            "suggestion": "Try using a smaller image or increase maxFileSize",
                        },
                    )

                buffer = response.content

            if len(buffer) > self.max_file_size:
                size_mb = len(buffer) / 1024 / 1024
                max_mb = self.max_file_size / 1024 / 1024
                raise InvalidImageError(
                    f"Downloaded file too large: {size_mb:.2f}MB (max: {max_mb:.2f}MB)",
                    {
                        "url": image_url,
                        "fileSize": len(buffer),
                        "maxSize": self.max_file_size,
                    },
                )

            is_valid, _ = self._validate_image_data(buffer)
            if not is_valid:
                raise InvalidImageError(
                    f"Downloaded file is not a valid image: {image_url}",
                    {
                        "url": image_url,
                        "suggestion": "Make sure the URL points to an actual image file",
                    },
                )

            local_path.write_bytes(buffer)

            logger.debug(
                f"Image downloaded successfully: {local_path} ({len(buffer)} bytes)"
            )

            return {
                "originalUrl": image_url,
                "localPath": str(local_path),
                "cached": False,
                "fileSize": len(buffer),
            }

        except InvalidImageError:
            raise
        except (httpx.TimeoutException, asyncio.TimeoutError) as error:
            raise InvalidImageError(
                f"Image download timeout after {self.timeout}ms: {image_url}",
                {
                    "url": image_url,
                    "timeout": self.timeout,
                    "suggestion": "The image may be too large or the network is slow",
                },
                error,
            ) from error
        except Exception as error:
            raise InvalidImageError(
                f"Failed to download image: {image_url}",
                {"url": image_url},
                error,
            ) from error

    async def download_images(self, image_urls: list[str]) -> list[DownloadResult]:
        """Download several images concurrently, reporting all failures together."""
        results = await asyncio.gather(
            *(self.download_image(url) for url in image_urls),
            return_exceptions=True,
        )

        success_results: list[DownloadResult] = []
        errors: list[tuple[str, BaseException]] = []

        for url, result in zip(image_urls, results, strict=True):
            if isinstance(result, BaseException):
                errors.append((url, result))
            else:
                success_results.append(result)

        if errors:
            error_messages = "\n".join(f"{url}: {error}" for url, error in errors)
            raise InvalidImageError(
                f"Failed to download {len(errors)} of {len(image_urls)} images:\n"
                f"{error_messages}",
                {
                    "totalCount": len(image_urls),
                    "failedCount": len(errors),
                    "successCount": len(success_results),
                    "failedUrls": [url for url, _ in errors],
                },
            )

        return success_results

    async def process_image_paths(self, image_paths: list[str]) -> list[str]:
        """Resolve a mixed list of URLs and local paths to local paths.

        Local paths keep their original relative order and come first; downloaded
        files follow in URL order.
        """
        local_paths: list[str] = []
        urls_to_download: list[str] = []

        for path in image_paths:
            if self.is_image_url(path):
                urls_to_download.append(path)
            else:
                if not Path(path).exists():
                    raise InvalidImageError(
                        f"Local image file not found: {path}",
                        {
                            "path": path,
                            "suggestion": (
                                "Make sure the file path is correct and the file exists"
                            ),
                        },
                    )
                local_paths.append(path)

        if urls_to_download:
            logger.debug(f"Downloading {len(urls_to_download)} images from URLs...")
            download_results = await self.download_images(urls_to_download)
            local_paths.extend(result["localPath"] for result in download_results)

            cached_count = sum(1 for r in download_results if r["cached"])
            new_count = len(download_results) - cached_count
            logger.debug(
                f"Downloaded {new_count} new images, used {cached_count} cached images"
            )

        if not local_paths:
            raise InvalidImageError(
                "No valid images found",
                {
                    "providedPaths": len(image_paths),
                    "suggestion": "Provide at least one valid image URL or local file path",
                },
            )

        return local_paths

    def get_save_dir(self) -> str:
        return self.save_dir


_default_downloader: ImageDownloader | None = None


def get_image_downloader(save_dir: str | None = None) -> ImageDownloader:
    global _default_downloader
    if _default_downloader is None or (
        save_dir and _default_downloader.get_save_dir() != save_dir
    ):
        _default_downloader = ImageDownloader(save_dir or "./temp_images")
    return _default_downloader
