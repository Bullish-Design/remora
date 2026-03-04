"""Integration tests that use real Playwright browser.

These tests require Playwright browsers to be installed.
Run with: pytest browser_demo/tests/test_integration.py -m integration
"""

from __future__ import annotations

from pathlib import Path

import pytest

from browser_demo.clipper import Clipper, clip_url
from browser_demo.fetcher import PlaywrightFetcher
from browser_demo.store import ClipStore


pytestmark = pytest.mark.integration


class TestPlaywrightFetcherIntegration:
    async def test_fetch_example_com(self) -> None:
        async with PlaywrightFetcher(executable_path="auto") as fetcher:
            result = await fetcher.fetch("https://example.com", wait_until="domcontentloaded")
        assert result.ok
        assert result.status_code == 200
        assert "Example Domain" in result.title
        assert "<html" in result.html.lower()
        assert result.final_url.startswith("https://example.com")

    async def test_fetch_nonexistent_raises(self) -> None:
        """Fetching a completely bogus URL should raise or return an error."""
        async with PlaywrightFetcher(executable_path="auto") as fetcher:
            # This should fail in some way (timeout or DNS error)
            with pytest.raises(Exception):
                await fetcher.fetch("https://this-domain-does-not-exist-xyz123.com", timeout_ms=5000)


class TestClipUrlIntegration:
    async def test_clip_example_com(self, tmp_clips_dir: Path) -> None:
        record = await clip_url(
            "https://example.com",
            clips_dir=tmp_clips_dir,
            tags=["integration", "test"],
        )
        assert record.title == "Example Domain"
        assert record.url.startswith("https://example.com")
        assert record.tags == ["integration", "test"]
        assert "Example Domain" in record.content
        assert record.metadata.content_hash != ""

        # Verify file exists
        file_path = tmp_clips_dir / record.filename()
        assert file_path.exists()

        # Verify store has it
        store = ClipStore(tmp_clips_dir)
        try:
            assert store.count() == 1
            retrieved = store.get(record.clip_id)
            assert retrieved is not None
            assert retrieved.title == "Example Domain"
        finally:
            store.close()

    async def test_clip_with_selector(self, tmp_clips_dir: Path) -> None:
        record = await clip_url(
            "https://example.com",
            clips_dir=tmp_clips_dir,
            selector="div",
        )
        # example.com has a single div with the content
        assert "Example Domain" in record.content
