"""Graph state reader with WAL-based change detection."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

logger = logging.getLogger("remora.web")


@dataclass
class GraphSnapshot:
    """Immutable snapshot of the current graph state."""

    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    cursor_focus: dict | None = None
    timestamp: float = 0.0


class GraphState:
    """Reads the Remora SQLite DB and yields snapshots on change.

    Change detection strategy:
    1. Primary: watch the WAL file mtime via watchfiles (if available)
    2. Fallback: poll max(rowid) every 0.5s
    """

    def __init__(self, db_path: str = ".remora/indexer.db") -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._last_fingerprint: str = ""

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def read_snapshot(self) -> GraphSnapshot:
        """Read a full snapshot of nodes, edges, and cursor focus."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # Nodes
        cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
        nodes = [dict(row) for row in cursor.fetchall()]
        # Normalize id -> remora_id
        for n in nodes:
            if "id" in n:
                n["remora_id"] = n.pop("id")

        # Edges
        cursor.execute("SELECT * FROM edges")
        edges = [dict(row) for row in cursor.fetchall()]

        # Cursor focus
        cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
        row = cursor.fetchone()
        cursor_focus = dict(row) if row else None

        return GraphSnapshot(
            nodes=nodes,
            edges=edges,
            cursor_focus=cursor_focus,
            timestamp=time.time(),
        )

    def read_node(self, node_id: str) -> dict | None:
        """Read a single node by id."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if "id" in d:
            d["remora_id"] = d.pop("id")
        return d

    def read_recent_events(self, agent_id: str, limit: int = 10) -> list[dict]:
        """Read recent events for a specific agent."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_id, event_type, timestamp, correlation_id, agent_id, payload
            FROM events
            WHERE agent_id = ? OR json_extract(payload, '$.to_agent') = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (agent_id, agent_id, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def _fingerprint(self) -> str:
        """Compute a lightweight fingerprint of DB state."""
        conn = self._get_conn()
        cursor = conn.cursor()
        parts = []
        # Node count + max rowid
        cursor.execute("SELECT count(*), max(rowid) FROM nodes")
        row = cursor.fetchone()
        parts.append(f"n:{row[0]}:{row[1]}")
        # Edge count
        cursor.execute("SELECT count(*) FROM edges")
        parts.append(f"e:{cursor.fetchone()[0]}")
        # Cursor focus timestamp
        cursor.execute("SELECT timestamp FROM cursor_focus WHERE id = 1")
        cf = cursor.fetchone()
        parts.append(f"cf:{cf[0] if cf else 0}")
        # Latest event
        cursor.execute("SELECT max(rowid) FROM events")
        parts.append(f"ev:{cursor.fetchone()[0]}")
        return "|".join(parts)

    async def changes(self) -> AsyncIterator[GraphSnapshot]:
        """Async iterator that yields a snapshot whenever the DB changes.

        Tries watchfiles for efficient WAL monitoring, falls back to polling.
        """
        try:
            await self._watch_wal()
            return  # pragma: no cover
        except Exception:
            pass

        # Fallback: poll fingerprint
        async for snapshot in self._poll_changes():
            yield snapshot

    async def _poll_changes(self) -> AsyncIterator[GraphSnapshot]:
        """Poll-based change detection."""
        while True:
            await asyncio.sleep(0.5)
            try:
                fp = await asyncio.to_thread(self._fingerprint)
                if fp != self._last_fingerprint:
                    self._last_fingerprint = fp
                    snapshot = await asyncio.to_thread(self.read_snapshot)
                    yield snapshot
            except Exception:
                logger.debug("Poll error", exc_info=True)
                await asyncio.sleep(2.0)

    async def _watch_wal(self) -> AsyncIterator[GraphSnapshot]:
        """Watch the WAL file for changes using watchfiles."""
        try:
            from watchfiles import awatch, Change
        except ImportError:
            raise RuntimeError("watchfiles not available")

        wal_path = str(self.db_path) + "-wal"
        if not Path(wal_path).exists():
            raise RuntimeError("WAL file does not exist yet")

        async for _changes in awatch(wal_path, poll_delay_ms=200):
            try:
                fp = await asyncio.to_thread(self._fingerprint)
                if fp != self._last_fingerprint:
                    self._last_fingerprint = fp
                    snapshot = await asyncio.to_thread(self.read_snapshot)
                    yield snapshot
            except Exception:
                logger.debug("WAL watch error", exc_info=True)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
