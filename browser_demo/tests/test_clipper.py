"""Tests for browser_demo.clipper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from browser_demo.clipper import ClipError, Clipper
from browser_demo.fetcher import PlaywrightFetcher, _find_system_chromium
from browser_demo.models import FetchResult
from browser_demo.store import ClipStore


class MockFetcher:
    """Mock fetcher that returns pre-configured results."""

    def __init__(self, result: FetchResult) -> None:
        self._result = result
        self.fetch_calls: list[dict] = []

    async def fetch(self, url: str, *, wait_until: str = "networkidle", timeout_ms: int = 30000) -> FetchResult:
        self.fetch_calls.append({"url": url, "wait_until": wait_until, "timeout_ms": timeout_ms})
        return self._result


class TestClipper:
    @pytest.fixture
    def mock_fetcher(self, sample_html: str) -> MockFetcher:
        return MockFetcher(
            FetchResult(
                url="https://example.com/test",
                final_url="https://example.com/test",
                title="Test Page Title",
                html=sample_html,
                status_code=200,
            )
        )

    @pytest.fixture
    def clipper(self, store: ClipStore, mock_fetcher: MockFetcher) -> Clipper:
        return Clipper(store=store, fetcher=mock_fetcher)

    async def test_clip_basic(self, clipper: Clipper, store: ClipStore) -> None:
        record = await clipper.clip("https://example.com/test")
        assert record.url == "https://example.com/test"
        assert record.title == "Test Page Title"
        assert "Welcome to the Test Page" in record.content
        # Should be saved in store
        assert store.count() == 1

    async def test_clip_with_tags(self, clipper: Clipper) -> None:
        record = await clipper.clip("https://example.com/test", tags=["python", "docs"])
        assert record.tags == ["python", "docs"]

    async def test_clip_with_selector(self, clipper: Clipper) -> None:
        record = await clipper.clip("https://example.com/test", selector="article")
        # Should have the article content
        assert "Welcome to the Test Page" in record.content

    async def test_clip_with_strip_images(self, clipper: Clipper) -> None:
        record = await clipper.clip("https://example.com/test", strip_images=True)
        assert "cat.jpg" not in record.content

    async def test_clip_records_fetcher_args(self, clipper: Clipper, mock_fetcher: MockFetcher) -> None:
        await clipper.clip("https://example.com/test", wait_until="load", timeout_ms=5000)
        assert len(mock_fetcher.fetch_calls) == 1
        assert mock_fetcher.fetch_calls[0]["url"] == "https://example.com/test"
        assert mock_fetcher.fetch_calls[0]["wait_until"] == "load"
        assert mock_fetcher.fetch_calls[0]["timeout_ms"] == 5000

    async def test_clip_http_error_raises(self, store: ClipStore) -> None:
        error_fetcher = MockFetcher(FetchResult(url="u", final_url="u", title="", html="", status_code=404))
        clipper = Clipper(store=store, fetcher=error_fetcher)
        with pytest.raises(ClipError, match="HTTP 404"):
            await clipper.clip("https://example.com/404")

    async def test_clip_saves_file_on_disk(self, clipper: Clipper, tmp_clips_dir: Path) -> None:
        record = await clipper.clip("https://example.com/test")
        # File should exist
        expected_file = tmp_clips_dir / record.filename()
        assert expected_file.exists()
        content = expected_file.read_text()
        assert "---" in content
        assert "Welcome to the Test Page" in content

    async def test_clip_content_hash_populated(self, clipper: Clipper) -> None:
        record = await clipper.clip("https://example.com/test")
        assert record.metadata.content_hash != ""
        assert len(record.metadata.content_hash) == 16

    async def test_clip_uses_final_url(self, store: ClipStore) -> None:
        """If the page redirects, the stored URL should be the final URL."""
        redirect_fetcher = MockFetcher(
            FetchResult(
                url="https://example.com/old",
                final_url="https://example.com/new",
                title="Redirected",
                html="<h1>Redirected</h1><p>Hello</p>",
                status_code=200,
            )
        )
        clipper = Clipper(store=store, fetcher=redirect_fetcher)
        record = await clipper.clip("https://example.com/old")
        assert record.url == "https://example.com/new"


class TestFindSystemChromium:
    def test_finds_chromium_when_available(self) -> None:
        with patch("browser_demo.fetcher.shutil.which", return_value="/usr/bin/chromium"):
            result = _find_system_chromium()
        assert result == "/usr/bin/chromium"

    def test_finds_chromium_browser_when_chromium_missing(self) -> None:
        def mock_which(name: str) -> str | None:
            if name == "chromium":
                return None
            if name == "chromium-browser":
                return "/usr/bin/chromium-browser"
            return None

        with patch("browser_demo.fetcher.shutil.which", side_effect=mock_which):
            result = _find_system_chromium()
        assert result == "/usr/bin/chromium-browser"

    def test_returns_none_when_no_chromium_found(self) -> None:
        with patch("browser_demo.fetcher.shutil.which", return_value=None):
            result = _find_system_chromium()
        assert result is None


class TestPlaywrightFetcherInit:
    def test_accepts_executable_path(self) -> None:
        fetcher = PlaywrightFetcher(executable_path="/usr/bin/chromium")
        assert fetcher._executable_path == "/usr/bin/chromium"

    def test_executable_path_defaults_to_none(self) -> None:
        fetcher = PlaywrightFetcher()
        assert fetcher._executable_path is None
