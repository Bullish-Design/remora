"""Graph state reader with WAL-based change detection for the graph viewer."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

logger = logging.getLogger("remora.graph")


@dataclass
class GraphSnapshot:
    """Immutable snapshot of current graph state."""

    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    cursor_focus: dict | None = None
    timestamp: float = 0.0


class GraphState:
    """Reads the Remora SQLite DB and yields snapshots on change."""

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

        cursor.execute("SELECT * FROM nodes WHERE status != 'orphaned'")
        nodes = [dict(row) for row in cursor.fetchall()]
        for n in nodes:
            if "id" in n:
                n["remora_id"] = n.pop("id")

        cursor.execute("SELECT * FROM edges")
        edges = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
        row = cursor.fetchone()
        cursor_focus = dict(row) if row else None

        return GraphSnapshot(nodes=nodes, edges=edges, cursor_focus=cursor_focus, timestamp=time.time())

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

    def read_events_for_agent(self, agent_id: str, limit: int = 20) -> list[dict]:
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

    def read_proposals_for_agent(self, agent_id: str) -> list[dict]:
        """Read pending proposals for a specific agent."""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM proposals WHERE agent_id = ? AND status = 'pending'",
            (agent_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def read_edges_for_node(self, node_id: str) -> dict:
        """Read connections for a node: parents, children, callers, callees."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'parent_of'",
            (node_id,),
        )
        parents = [row["from_id"] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'parent_of'",
            (node_id,),
        )
        children = [row["to_id"] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT from_id FROM edges WHERE to_id = ? AND edge_type = 'calls'",
            (node_id,),
        )
        callers = [row["from_id"] for row in cursor.fetchall()]

        cursor.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'calls'",
            (node_id,),
        )
        callees = [row["to_id"] for row in cursor.fetchall()]

        return {"parents": parents, "children": children, "callers": callers, "callees": callees}

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Write a command to the queue (uses a separate writable connection)."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO command_queue (command_type, agent_id, payload, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (command_type, agent_id, json.dumps(payload), time.time()),
        )
        conn.commit()
        cmd_id = cursor.lastrowid
        conn.close()
        return cmd_id

    def _fingerprint(self) -> str:
        """Compute a lightweight fingerprint of DB state."""
        conn = self._get_conn()
        cursor = conn.cursor()
        parts = []

        cursor.execute("SELECT count(*), max(rowid) FROM nodes")
        row = cursor.fetchone()
        parts.append(f"n:{row[0]}:{row[1]}")

        cursor.execute("SELECT count(*) FROM edges")
        parts.append(f"e:{cursor.fetchone()[0]}")

        cursor.execute("SELECT timestamp FROM cursor_focus WHERE id = 1")
        cf = cursor.fetchone()
        parts.append(f"cf:{cf[0] if cf else 0}")

        cursor.execute("SELECT max(rowid) FROM events")
        parts.append(f"ev:{cursor.fetchone()[0]}")

        cursor.execute("SELECT max(rowid) FROM proposals")
        parts.append(f"pr:{cursor.fetchone()[0]}")

        return "|".join(parts)

    async def changes(self) -> AsyncIterator[GraphSnapshot]:
        """Yield snapshots whenever the DB changes (poll-based)."""
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

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
