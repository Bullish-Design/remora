"""Tests for browser_demo.models."""

from __future__ import annotations

from datetime import datetime, timezone

from browser_demo.models import ClipMetadata, ClipRecord, FetchResult


class TestClipMetadata:
    def test_default_fields(self) -> None:
        meta = ClipMetadata(url="https://example.com")
        assert meta.url == "https://example.com"
        assert meta.title == ""
        assert meta.tags == []
        assert meta.selector is None
        assert meta.content_hash == ""
        assert len(meta.clip_id) == 12  # hex UUID prefix

    def test_compute_hash(self) -> None:
        meta = ClipMetadata(url="https://example.com")
        h = meta.compute_hash("hello world")
        assert len(h) == 16
        assert meta.content_hash == h
        # Same content -> same hash
        assert meta.compute_hash("hello world") == h
        # Different content -> different hash
        assert meta.compute_hash("goodbye") != h

    def test_tags_and_selector(self) -> None:
        meta = ClipMetadata(url="https://example.com", tags=["python", "async"], selector="article")
        assert meta.tags == ["python", "async"]
        assert meta.selector == "article"


class TestClipRecord:
    def test_properties_delegate_to_metadata(self, sample_record: ClipRecord) -> None:
        assert sample_record.clip_id == "abc123"
        assert sample_record.url == "https://example.com/test"
        assert sample_record.title == "Test Page"
        assert sample_record.tags == ["python", "testing"]

    def test_to_frontmatter_markdown(self, sample_record: ClipRecord) -> None:
        md = sample_record.to_frontmatter_markdown()
        assert md.startswith("---\n")
        assert "url: https://example.com/test" in md
        assert "title: Test Page" in md
        assert "clip_id: abc123" in md
        assert "---\n\n# Test Page" in md
        assert "Some content here." in md

    def test_from_frontmatter_markdown_roundtrip(self, sample_record: ClipRecord) -> None:
        md = sample_record.to_frontmatter_markdown()
        restored = ClipRecord.from_frontmatter_markdown(md)
        assert restored.clip_id == sample_record.clip_id
        assert restored.url == sample_record.url
        assert restored.title == sample_record.title
        assert restored.tags == sample_record.tags
        assert restored.content == sample_record.content
        assert restored.metadata.content_hash == sample_record.metadata.content_hash

    def test_from_frontmatter_markdown_invalid(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid frontmatter"):
            ClipRecord.from_frontmatter_markdown("no frontmatter here")

    def test_filename_generation(self, sample_record: ClipRecord) -> None:
        name = sample_record.filename()
        assert name.endswith(".md")
        assert "test-page" in name
        # Starts with date
        assert name[:10].replace("-", "").isdigit()

    def test_filename_empty_title_uses_id(self) -> None:
        meta = ClipMetadata(url="https://example.com", clip_id="xyz789")
        record = ClipRecord(metadata=meta, content="content")
        name = record.filename()
        assert "xyz789" in name

    def test_filename_special_chars_slugified(self) -> None:
        meta = ClipMetadata(url="https://example.com", title="Hello World! @#$ & More")
        record = ClipRecord(metadata=meta, content="content")
        name = record.filename()
        # Should not contain special chars
        assert "!" not in name
        assert "@" not in name
        assert "$" not in name


class TestFetchResult:
    def test_ok_for_200(self) -> None:
        r = FetchResult(url="u", final_url="u", title="t", html="h", status_code=200)
        assert r.ok is True

    def test_ok_for_301(self) -> None:
        r = FetchResult(url="u", final_url="u", title="t", html="h", status_code=301)
        assert r.ok is True

    def test_not_ok_for_404(self) -> None:
        r = FetchResult(url="u", final_url="u", title="t", html="h", status_code=404)
        assert r.ok is False

    def test_not_ok_for_500(self) -> None:
        r = FetchResult(url="u", final_url="u", title="t", html="h", status_code=500)
        assert r.ok is False
