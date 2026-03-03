"""Tests for browser_demo.store."""

from __future__ import annotations

from pathlib import Path

from browser_demo.models import ClipMetadata, ClipRecord
from browser_demo.store import ClipStore


class TestClipStore:
    def test_save_creates_file_and_index_entry(
        self, store: ClipStore, sample_record: ClipRecord, tmp_clips_dir: Path
    ) -> None:
        file_path = store.save(sample_record)
        assert file_path.exists()
        assert file_path.suffix == ".md"
        # Content hash should be computed
        assert sample_record.metadata.content_hash != ""

    def test_save_and_get_roundtrip(self, store: ClipStore, sample_record: ClipRecord) -> None:
        store.save(sample_record)
        retrieved = store.get(sample_record.clip_id)
        assert retrieved is not None
        assert retrieved.clip_id == sample_record.clip_id
        assert retrieved.url == sample_record.url
        assert retrieved.title == sample_record.title
        assert retrieved.tags == sample_record.tags
        assert retrieved.content == sample_record.content

    def test_get_nonexistent_returns_none(self, store: ClipStore) -> None:
        assert store.get("nonexistent") is None

    def test_get_by_url(self, store: ClipStore, sample_record: ClipRecord) -> None:
        store.save(sample_record)
        result = store.get_by_url("https://example.com/test")
        assert result is not None
        assert result.clip_id == sample_record.clip_id

    def test_get_by_url_nonexistent(self, store: ClipStore) -> None:
        assert store.get_by_url("https://nope.com") is None

    def test_list_all(self, store: ClipStore) -> None:
        for i in range(5):
            meta = ClipMetadata(url=f"https://example.com/{i}", title=f"Page {i}", clip_id=f"clip_{i}")
            record = ClipRecord(metadata=meta, content=f"Content {i}")
            store.save(record)

        clips = store.list_all()
        assert len(clips) == 5

    def test_list_all_with_limit(self, store: ClipStore) -> None:
        for i in range(10):
            meta = ClipMetadata(url=f"https://example.com/{i}", title=f"Page {i}", clip_id=f"clip_{i}")
            record = ClipRecord(metadata=meta, content=f"Content {i}")
            store.save(record)

        clips = store.list_all(limit=3)
        assert len(clips) == 3

    def test_count(self, store: ClipStore) -> None:
        assert store.count() == 0

        meta = ClipMetadata(url="https://example.com", clip_id="c1")
        store.save(ClipRecord(metadata=meta, content="x"))
        assert store.count() == 1

        meta2 = ClipMetadata(url="https://example.com/2", clip_id="c2")
        store.save(ClipRecord(metadata=meta2, content="y"))
        assert store.count() == 2

    def test_delete(self, store: ClipStore, sample_record: ClipRecord, tmp_clips_dir: Path) -> None:
        file_path = store.save(sample_record)
        assert file_path.exists()
        assert store.count() == 1

        result = store.delete(sample_record.clip_id)
        assert result is True
        assert not file_path.exists()
        assert store.count() == 0

    def test_delete_nonexistent(self, store: ClipStore) -> None:
        assert store.delete("nonexistent") is False

    def test_search_by_title(self, store: ClipStore) -> None:
        meta = ClipMetadata(url="https://example.com", title="Python asyncio tutorial", clip_id="s1")
        store.save(ClipRecord(metadata=meta, content="Learn about async/await."))

        meta2 = ClipMetadata(url="https://example.com/2", title="JavaScript promises", clip_id="s2")
        store.save(ClipRecord(metadata=meta2, content="Promises are async too."))

        results = store.search("Python")
        assert len(results) >= 1
        assert any(r.clip_id == "s1" for r in results)

    def test_search_by_content(self, store: ClipStore) -> None:
        meta = ClipMetadata(url="https://example.com", title="Page One", clip_id="sc1")
        store.save(ClipRecord(metadata=meta, content="The quick brown fox jumps over the lazy dog."))

        results = store.search("fox")
        assert len(results) >= 1
        assert results[0].clip_id == "sc1"

    def test_search_by_tag(self, store: ClipStore) -> None:
        meta = ClipMetadata(url="https://example.com", title="Tagged", tags=["python", "web"], clip_id="t1")
        store.save(ClipRecord(metadata=meta, content="content"))

        results = store.search_by_tag("python")
        assert len(results) == 1
        assert results[0].clip_id == "t1"

        results = store.search_by_tag("rust")
        assert len(results) == 0

    def test_search_no_results(self, store: ClipStore) -> None:
        results = store.search("nonexistent_query_xyz")
        assert results == []

    def test_upsert_overwrites_existing(self, store: ClipStore) -> None:
        meta = ClipMetadata(url="https://example.com", title="Version 1", clip_id="up1")
        store.save(ClipRecord(metadata=meta, content="First version"))
        assert store.count() == 1

        # Save again with same ID, different content
        meta2 = ClipMetadata(url="https://example.com", title="Version 2", clip_id="up1")
        store.save(ClipRecord(metadata=meta2, content="Second version"))
        assert store.count() == 1

        record = store.get("up1")
        assert record is not None
        assert record.title == "Version 2"
        assert record.content == "Second version"

    def test_missing_file_returns_placeholder(
        self, store: ClipStore, sample_record: ClipRecord, tmp_clips_dir: Path
    ) -> None:
        file_path = store.save(sample_record)
        # Delete the file but leave the DB entry
        file_path.unlink()

        record = store.get(sample_record.clip_id)
        assert record is not None
        assert "[clip file missing]" in record.content
