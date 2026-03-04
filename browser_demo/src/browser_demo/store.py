"""SQLite-backed clip index store."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from browser_demo.models import ClipMetadata, ClipRecord


class ClipStore:
    """SQLite index for web clips, with markdown files on disk."""

    def __init__(self, clips_dir: Path) -> None:
        self.clips_dir = clips_dir
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.clips_dir / "index.db"
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _ensure_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS clips (
                clip_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                clipped_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                selector TEXT,
                content_hash TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clips_url ON clips(url);
            CREATE INDEX IF NOT EXISTS idx_clips_clipped_at ON clips(clipped_at);
        """)
        # FTS virtual table for full-text search on title + content
        self.conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS clips_fts USING fts5(
                clip_id,
                title,
                content,
                tags
            );
        """)
        self.conn.commit()

    def save(self, record: ClipRecord) -> Path:
        """Save a clip to disk and index it in SQLite. Returns the file path."""
        # Compute content hash
        record.metadata.compute_hash(record.content)

        # Write markdown file
        filename = record.filename()
        file_path = self.clips_dir / filename
        file_path.write_text(record.to_frontmatter_markdown(), encoding="utf-8")

        tags_json = json.dumps(record.metadata.tags)

        # Upsert into index
        self.conn.execute(
            """
            INSERT INTO clips (clip_id, url, title, clipped_at, tags, selector, content_hash, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(clip_id) DO UPDATE SET
                url=excluded.url, title=excluded.title, clipped_at=excluded.clipped_at,
                tags=excluded.tags, selector=excluded.selector,
                content_hash=excluded.content_hash, file_path=excluded.file_path
            """,
            (
                record.metadata.clip_id,
                record.metadata.url,
                record.metadata.title,
                record.metadata.clipped_at.isoformat(),
                tags_json,
                record.metadata.selector,
                record.metadata.content_hash,
                str(file_path.relative_to(self.clips_dir)),
            ),
        )

        # Upsert FTS
        self.conn.execute("DELETE FROM clips_fts WHERE clip_id = ?", (record.metadata.clip_id,))
        self.conn.execute(
            "INSERT INTO clips_fts (clip_id, title, content, tags) VALUES (?, ?, ?, ?)",
            (record.metadata.clip_id, record.metadata.title, record.content, " ".join(record.metadata.tags)),
        )
        self.conn.commit()
        return file_path

    def get(self, clip_id: str) -> ClipRecord | None:
        """Retrieve a clip by ID."""
        row = self.conn.execute("SELECT * FROM clips WHERE clip_id = ?", (clip_id,)).fetchone()
        if row is None:
            return None
        return self._load_record(row)

    def get_by_url(self, url: str) -> ClipRecord | None:
        """Retrieve the most recent clip for a given URL."""
        row = self.conn.execute("SELECT * FROM clips WHERE url = ? ORDER BY clipped_at DESC LIMIT 1", (url,)).fetchone()
        if row is None:
            return None
        return self._load_record(row)

    def list_all(self, limit: int = 100, offset: int = 0) -> list[ClipMetadata]:
        """List clip metadata, ordered by most recent first."""
        rows = self.conn.execute(
            "SELECT * FROM clips ORDER BY clipped_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_metadata(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> list[ClipMetadata]:
        """Full-text search across clip titles, content, and tags."""
        rows = self.conn.execute(
            """
            SELECT c.* FROM clips c
            JOIN clips_fts f ON c.clip_id = f.clip_id
            WHERE clips_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [self._row_to_metadata(r) for r in rows]

    def search_by_tag(self, tag: str) -> list[ClipMetadata]:
        """Find clips that have a specific tag."""
        # Use JSON contains check
        rows = self.conn.execute(
            "SELECT * FROM clips WHERE tags LIKE ? ORDER BY clipped_at DESC",
            (f'%"{tag}"%',),
        ).fetchall()
        return [self._row_to_metadata(r) for r in rows]

    def delete(self, clip_id: str) -> bool:
        """Delete a clip by ID. Returns True if found and deleted."""
        row = self.conn.execute("SELECT file_path FROM clips WHERE clip_id = ?", (clip_id,)).fetchone()
        if row is None:
            return False

        # Remove file
        file_path = self.clips_dir / row["file_path"]
        if file_path.exists():
            file_path.unlink()

        # Remove from index
        self.conn.execute("DELETE FROM clips WHERE clip_id = ?", (clip_id,))
        self.conn.execute("DELETE FROM clips_fts WHERE clip_id = ?", (clip_id,))
        self.conn.commit()
        return True

    def count(self) -> int:
        """Return total number of clips."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM clips").fetchone()
        return row["cnt"] if row else 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _load_record(self, row: sqlite3.Row) -> ClipRecord:
        """Load a full ClipRecord from a DB row (reads the file from disk)."""
        file_path = self.clips_dir / row["file_path"]
        if not file_path.exists():
            # File missing — reconstruct with empty content
            metadata = self._row_to_metadata(row)
            return ClipRecord(metadata=metadata, content="[clip file missing]")
        text = file_path.read_text(encoding="utf-8")
        return ClipRecord.from_frontmatter_markdown(text)

    def _row_to_metadata(self, row: sqlite3.Row) -> ClipMetadata:
        """Convert a DB row to ClipMetadata."""
        tags = json.loads(row["tags"]) if row["tags"] else []
        return ClipMetadata(
            clip_id=row["clip_id"],
            url=row["url"],
            title=row["title"],
            clipped_at=datetime.fromisoformat(row["clipped_at"]),
            tags=tags,
            selector=row["selector"],
            content_hash=row["content_hash"],
        )
