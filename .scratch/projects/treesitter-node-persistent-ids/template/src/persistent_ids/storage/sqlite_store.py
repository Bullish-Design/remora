"""SQLite persistence wrapper for durable node IDs."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteStore:
    """Manage schema setup and transactional writes."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self, schema_path: Path) -> None:
        """Apply SQL schema file."""

        sql = schema_path.read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()

    def close(self) -> None:
        """Close active SQLite connection."""

        self._conn.close()
