"""Tests for browser_demo.cli."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from browser_demo.cli import app
from browser_demo.models import ClipMetadata, ClipRecord
from browser_demo.store import ClipStore

runner = CliRunner()


class TestCliList:
    def test_list_empty(self, tmp_clips_dir: Path) -> None:
        result = runner.invoke(app, ["list", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "No clips found" in result.output

    def test_list_with_clips(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="Test Clip", clip_id="lc1", tags=["test"])
        store.save(ClipRecord(metadata=meta, content="Hello world"))
        store.close()

        result = runner.invoke(app, ["list", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "lc1" in result.output
        assert "Test Clip" in result.output


class TestCliShow:
    def test_show_existing(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="Show Me", clip_id="sh1")
        store.save(ClipRecord(metadata=meta, content="Visible content here"))
        store.close()

        result = runner.invoke(app, ["show", "sh1", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "Show Me" in result.output
        assert "Visible content here" in result.output

    def test_show_nonexistent(self, tmp_clips_dir: Path) -> None:
        result = runner.invoke(app, ["show", "nope", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_show_metadata_only(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="Meta Only", clip_id="mo1")
        store.save(ClipRecord(metadata=meta, content="Should not appear"))
        store.close()

        result = runner.invoke(app, ["show", "mo1", "--dir", str(tmp_clips_dir), "--meta"])
        assert result.exit_code == 0
        assert "Meta Only" in result.output
        # Content should not be in output when --meta is used
        # (title section and metadata are shown, but the content body is suppressed)
        assert "Should not appear" not in result.output


class TestCliSearch:
    def test_search_finds_clip(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="Python Tutorial", clip_id="se1")
        store.save(ClipRecord(metadata=meta, content="Learn Python basics"))
        store.close()

        result = runner.invoke(app, ["search", "Python", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "se1" in result.output
        assert "Python Tutorial" in result.output

    def test_search_no_results(self, tmp_clips_dir: Path) -> None:
        result = runner.invoke(app, ["search", "nonexistent_xyz", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "No results" in result.output


class TestCliDelete:
    def test_delete_with_force(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="To Delete", clip_id="del1")
        store.save(ClipRecord(metadata=meta, content="bye"))
        store.close()

        result = runner.invoke(app, ["delete", "del1", "--dir", str(tmp_clips_dir), "--force"])
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_delete_nonexistent(self, tmp_clips_dir: Path) -> None:
        result = runner.invoke(app, ["delete", "nope", "--dir", str(tmp_clips_dir), "--force"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCliExport:
    def test_export_content(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="Export Me", clip_id="exp1")
        store.save(ClipRecord(metadata=meta, content="# Exported Content\n\nHello."))
        store.close()

        result = runner.invoke(app, ["export", "exp1", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "# Exported Content" in result.output

    def test_export_with_frontmatter(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta = ClipMetadata(url="https://example.com", title="Export FM", clip_id="exp2")
        store.save(ClipRecord(metadata=meta, content="content"))
        store.close()

        result = runner.invoke(app, ["export", "exp2", "--dir", str(tmp_clips_dir), "--frontmatter"])
        assert result.exit_code == 0
        assert "---" in result.output
        assert "url:" in result.output

    def test_export_nonexistent(self, tmp_clips_dir: Path) -> None:
        result = runner.invoke(app, ["export", "nope", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 1


class TestCliTags:
    def test_tags_empty(self, tmp_clips_dir: Path) -> None:
        result = runner.invoke(app, ["tags", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "No tags found" in result.output

    def test_tags_with_data(self, store: ClipStore, tmp_clips_dir: Path) -> None:
        meta1 = ClipMetadata(url="https://a.com", title="A", clip_id="ta1", tags=["python", "web"])
        store.save(ClipRecord(metadata=meta1, content="a"))
        meta2 = ClipMetadata(url="https://b.com", title="B", clip_id="ta2", tags=["python", "cli"])
        store.save(ClipRecord(metadata=meta2, content="b"))
        store.close()

        result = runner.invoke(app, ["tags", "--dir", str(tmp_clips_dir)])
        assert result.exit_code == 0
        assert "python" in result.output
        assert "web" in result.output
        assert "cli" in result.output
