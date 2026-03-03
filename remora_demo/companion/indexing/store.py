"""SQLite-vec vector store for Companion.

A simple, single-file vector store using sqlite-vec extension.
Stores document chunks with embeddings and supports similarity search.
"""

import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sqlite_vec


@dataclass
class Chunk:
    """A chunk of content with its embedding."""

    id: str
    file_path: str
    content: str
    content_type: str  # "code" | "markdown" | "prose"
    chunk_type: str  # "function" | "class" | "section" | "paragraph"
    start_line: int
    end_line: int
    name: str | None = None  # Function/class/section name
    parent: str | None = None  # Containing scope
    metadata: dict[str, Any] | None = None
    embedding: np.ndarray | None = None


@dataclass
class SearchResult:
    """Result from a similarity search."""

    chunk: Chunk
    score: float  # Similarity score (higher = more similar)
    distance: float  # L2 distance (lower = more similar)


def _serialize_f32(vector: np.ndarray) -> bytes:
    """Serialize a numpy array to bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector.astype(np.float32))


def _deserialize_f32(data: bytes, dim: int) -> np.ndarray:
    """Deserialize bytes to numpy array."""
    return np.array(struct.unpack(f"{dim}f", data), dtype=np.float32)


class VectorStore:
    """SQLite-vec based vector store.

    Stores chunks with embeddings and provides similarity search.
    All data stored in a single SQLite file.
    """

    def __init__(self, db_path: Path | str, embedding_dim: int) -> None:
        """Initialize the vector store.

        Args:
            db_path: Path to SQLite database file (created if doesn't exist)
            embedding_dim: Dimension of embedding vectors
        """
        self.db_path = Path(db_path)
        self.embedding_dim = embedding_dim
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get database connection, creating if needed."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self.conn.executescript(
            f"""
            -- Main chunks table with metadata
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                content_type TEXT NOT NULL,
                chunk_type TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                name TEXT,
                parent TEXT,
                metadata TEXT,  -- JSON
                created_at REAL DEFAULT (unixepoch('now'))
            );

            -- Vector index using sqlite-vec
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                id TEXT PRIMARY KEY,
                embedding float[{self.embedding_dim}]
            );

            -- Index for file path lookups
            CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path);

            -- Index for content type
            CREATE INDEX IF NOT EXISTS idx_chunks_content_type ON chunks(content_type);
            """
        )
        self.conn.commit()

    def add(self, chunk: Chunk) -> None:
        """Add a single chunk to the store."""
        self.add_many([chunk])

    def add_many(self, chunks: list[Chunk]) -> None:
        """Add multiple chunks to the store.

        More efficient than adding one at a time.
        """
        if not chunks:
            return

        # Insert into chunks table
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO chunks 
            (id, file_path, content, content_type, chunk_type, 
             start_line, end_line, name, parent, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.id,
                    c.file_path,
                    c.content,
                    c.content_type,
                    c.chunk_type,
                    c.start_line,
                    c.end_line,
                    c.name,
                    c.parent,
                    json.dumps(c.metadata) if c.metadata else None,
                )
                for c in chunks
            ],
        )

        # Insert into vector index
        vec_data = [(c.id, _serialize_f32(c.embedding)) for c in chunks if c.embedding is not None]
        if vec_data:
            self.conn.executemany(
                "INSERT OR REPLACE INTO vec_chunks (id, embedding) VALUES (?, ?)",
                vec_data,
            )

        self.conn.commit()

    def search(
        self,
        query_embedding: np.ndarray,
        limit: int = 10,
        content_type: str | None = None,
        file_path_prefix: str | None = None,
    ) -> list[SearchResult]:
        """Search for similar chunks.

        Args:
            query_embedding: Query vector
            limit: Maximum number of results
            content_type: Filter by content type (e.g., "code", "markdown")
            file_path_prefix: Filter by file path prefix

        Returns:
            List of SearchResult ordered by similarity (best first)
        """
        query_bytes = _serialize_f32(query_embedding)

        # sqlite-vec requires k=? in the WHERE clause for KNN queries
        # We do a two-step query: first get candidates from vec, then filter

        if content_type or file_path_prefix:
            # With filters: get more candidates, then filter
            candidate_limit = limit * 5  # Get extra candidates for filtering

            sql = """
                SELECT 
                    c.id, c.file_path, c.content, c.content_type, c.chunk_type,
                    c.start_line, c.end_line, c.name, c.parent, c.metadata,
                    v.distance
                FROM (
                    SELECT id, distance 
                    FROM vec_chunks 
                    WHERE embedding MATCH ? AND k = ?
                ) v
                JOIN chunks c ON c.id = v.id
                WHERE 1=1
            """
            params: list[Any] = [query_bytes, candidate_limit]

            if content_type:
                sql += " AND c.content_type = ?"
                params.append(content_type)

            if file_path_prefix:
                sql += " AND c.file_path LIKE ?"
                params.append(f"{file_path_prefix}%")

            sql += f" ORDER BY v.distance LIMIT {limit}"
        else:
            # No filters: simple KNN query
            sql = """
                SELECT 
                    c.id, c.file_path, c.content, c.content_type, c.chunk_type,
                    c.start_line, c.end_line, c.name, c.parent, c.metadata,
                    v.distance
                FROM (
                    SELECT id, distance 
                    FROM vec_chunks 
                    WHERE embedding MATCH ? AND k = ?
                ) v
                JOIN chunks c ON c.id = v.id
                ORDER BY v.distance
            """
            params = [query_bytes, limit]

        results = []
        for row in self.conn.execute(sql, params):
            chunk = Chunk(
                id=row[0],
                file_path=row[1],
                content=row[2],
                content_type=row[3],
                chunk_type=row[4],
                start_line=row[5],
                end_line=row[6],
                name=row[7],
                parent=row[8],
                metadata=json.loads(row[9]) if row[9] else None,
            )
            distance = row[10]
            # Convert L2 distance to similarity score (1 / (1 + distance))
            score = 1.0 / (1.0 + distance)
            results.append(SearchResult(chunk=chunk, score=score, distance=distance))

        return results

    def delete_by_file(self, file_path: str) -> int:
        """Delete all chunks from a specific file.

        Args:
            file_path: Path to the file

        Returns:
            Number of chunks deleted
        """
        # Get IDs to delete
        ids = [row[0] for row in self.conn.execute("SELECT id FROM chunks WHERE file_path = ?", (file_path,))]

        if not ids:
            return 0

        # Delete from both tables
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(f"DELETE FROM vec_chunks WHERE id IN ({placeholders})", ids)
        self.conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", ids)
        self.conn.commit()

        return len(ids)

    def get_by_id(self, chunk_id: str) -> Chunk | None:
        """Get a chunk by its ID."""
        row = self.conn.execute(
            """
            SELECT id, file_path, content, content_type, chunk_type,
                   start_line, end_line, name, parent, metadata
            FROM chunks WHERE id = ?
            """,
            (chunk_id,),
        ).fetchone()

        if not row:
            return None

        return Chunk(
            id=row[0],
            file_path=row[1],
            content=row[2],
            content_type=row[3],
            chunk_type=row[4],
            start_line=row[5],
            end_line=row[6],
            name=row[7],
            parent=row[8],
            metadata=json.loads(row[9]) if row[9] else None,
        )

    def list_files(self) -> list[str]:
        """List all indexed file paths."""
        return [row[0] for row in self.conn.execute("SELECT DISTINCT file_path FROM chunks ORDER BY file_path")]

    def count(self) -> int:
        """Return total number of chunks."""
        return self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def stats(self) -> dict[str, Any]:
        """Return store statistics."""
        return {
            "total_chunks": self.count(),
            "total_files": len(self.list_files()),
            "by_content_type": dict(
                self.conn.execute("SELECT content_type, COUNT(*) FROM chunks GROUP BY content_type").fetchall()
            ),
            "by_chunk_type": dict(
                self.conn.execute("SELECT chunk_type, COUNT(*) FROM chunks GROUP BY chunk_type").fetchall()
            ),
            "embedding_dim": self.embedding_dim,
            "db_path": str(self.db_path),
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
