"""Playwright-based headless browser page fetcher."""

from __future__ import annotations

import asyncio
import shutil
from typing import Protocol

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from browser_demo.models import FetchResult


def _find_system_chromium() -> str | None:
    """Find a system-installed Chromium binary.

    Checks common binary names in PATH order. Returns the path if found, None otherwise.
    This is useful on NixOS and similar systems where the Playwright-bundled Chromium
    can't find shared libraries.
    """
    for name in ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome"):
        path = shutil.which(name)
        if path:
            return path
    return None


class Fetcher(Protocol):
    """Protocol for page fetchers (allows mocking in tests)."""

    async def fetch(self, url: str, *, wait_until: str = "networkidle", timeout_ms: int = 30000) -> FetchResult: ...


class PlaywrightFetcher:
    """Fetch web pages using headless Chromium via Playwright.

    Usage:
        async with PlaywrightFetcher() as fetcher:
            result = await fetcher.fetch("https://example.com")

    On NixOS and similar systems where the Playwright-bundled Chromium fails to
    load shared libraries, set ``executable_path`` to the system chromium binary
    or let auto-detection find it (``executable_path="auto"``).
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        user_agent: str | None = None,
        executable_path: str | None = None,
    ) -> None:
        self._headless = headless
        self._user_agent = user_agent
        self._executable_path = executable_path
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> PlaywrightFetcher:
        self._pw = await async_playwright().start()

        launch_kwargs: dict = {"headless": self._headless}

        # Determine executable path: explicit > auto-detect > Playwright default
        exe = self._executable_path
        if exe == "auto":
            exe = _find_system_chromium()
        if exe:
            launch_kwargs["executable_path"] = exe

        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        context_kwargs: dict = {}
        if self._user_agent:
            context_kwargs["user_agent"] = self._user_agent
        self._context = await self._browser.new_context(**context_kwargs)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def fetch(
        self,
        url: str,
        *,
        wait_until: str = "networkidle",
        timeout_ms: int = 30000,
    ) -> FetchResult:
        """Fetch a URL and return the rendered HTML.

        Args:
            url: The URL to fetch.
            wait_until: Playwright wait strategy: 'load', 'domcontentloaded', 'networkidle'.
            timeout_ms: Maximum time to wait for the page in milliseconds.

        Returns:
            FetchResult with the rendered HTML and metadata.
        """
        if self._context is None:
            raise RuntimeError("PlaywrightFetcher must be used as an async context manager")

        page: Page = await self._context.new_page()
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            status_code = response.status if response else 0
            final_url = page.url
            title = await page.title()
            html = await page.content()

            return FetchResult(
                url=url,
                final_url=final_url,
                title=title,
                html=html,
                status_code=status_code,
            )
        finally:
            await page.close()
