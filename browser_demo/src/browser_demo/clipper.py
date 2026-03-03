"""Clipper orchestrator — fetch, convert, store pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path

from browser_demo.converter import extract_title, html_to_markdown
from browser_demo.fetcher import Fetcher, PlaywrightFetcher
from browser_demo.models import ClipMetadata, ClipRecord, FetchResult
from browser_demo.store import ClipStore


class Clipper:
    """Orchestrates the fetch -> convert -> store pipeline.

    Can be used with any Fetcher implementation (real Playwright or mock).
    """

    def __init__(self, store: ClipStore, fetcher: Fetcher) -> None:
        self.store = store
        self.fetcher = fetcher

    async def clip(
        self,
        url: str,
        *,
        tags: list[str] | None = None,
        selector: str | None = None,
        strip_images: bool = False,
        wait_until: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> ClipRecord:
        """Clip a URL: fetch the page, convert to markdown, save to store.

        Args:
            url: The URL to clip.
            tags: Optional list of tags.
            selector: Optional CSS selector to extract specific content.
            strip_images: If True, remove images from the output.
            wait_until: Playwright wait strategy.
            timeout_ms: Fetch timeout in milliseconds.

        Returns:
            The saved ClipRecord.
        """
        # Fetch
        result = await self.fetcher.fetch(url, wait_until=wait_until, timeout_ms=timeout_ms)

        if not result.ok:
            raise ClipError(f"Failed to fetch {url}: HTTP {result.status_code}")

        # Extract title (prefer fetched title, fall back to HTML extraction)
        title = result.title or extract_title(result.html)

        # Convert HTML to markdown
        content = html_to_markdown(result.html, selector=selector, strip_images=strip_images)

        # Build metadata
        metadata = ClipMetadata(
            url=result.final_url,
            title=title,
            tags=tags or [],
            selector=selector,
        )

        # Build record and save
        record = ClipRecord(metadata=metadata, content=content)
        self.store.save(record)

        return record


class ClipError(Exception):
    """Error during clipping."""


async def clip_url(
    url: str,
    clips_dir: Path,
    *,
    tags: list[str] | None = None,
    selector: str | None = None,
    strip_images: bool = False,
    headless: bool = True,
    executable_path: str | None = "auto",
) -> ClipRecord:
    """Convenience function: clip a URL in one call.

    Creates a PlaywrightFetcher and ClipStore, clips the URL, and returns the record.

    Args:
        url: The URL to clip.
        clips_dir: Directory to store clips.
        tags: Optional list of tags.
        selector: Optional CSS selector for content extraction.
        strip_images: If True, remove images from the output.
        headless: Run browser headless.
        executable_path: Path to chromium binary, "auto" to detect system chromium, or None for Playwright default.
    """
    store = ClipStore(clips_dir)
    try:
        async with PlaywrightFetcher(headless=headless, executable_path=executable_path) as fetcher:
            clipper = Clipper(store=store, fetcher=fetcher)
            return await clipper.clip(url, tags=tags, selector=selector, strip_images=strip_images)
    finally:
        store.close()
