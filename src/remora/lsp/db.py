# src/remora/lsp/db.py
from __future__ import annotations

import asyncio
import functools
import json
import threading
import time
from pathlib import Path
from typing import ParamSpec, TypeVar

import sqlite3

from remora.lsp.models import AgentEvent

P = ParamSpec("P")
R = TypeVar("R")


def async_db(fn):
    """Decorator: run sync DB method in a thread."""

    @functools.wraps(fn)
    async def wrapper(self, *args: P.args, **kwargs: P.kwargs) -> R:
        def _locked():
            with self._lock:
                return fn(self, *args, **kwargs)

        return await asyncio.to_thread(_locked)

    return wrapper


class RemoraDB:
    """LSP-specific database for proposals, events, edges, cursor focus, and commands.

    Node state lives in EventStore (core). This DB holds LSP-specific operational
    state that doesn't belong in the event-sourced core.
    """

    def __init__(self, db_path: str = ".remora/indexer.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS edges (
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                PRIMARY KEY (from_id, to_id, edge_type)
            );

            CREATE TABLE IF NOT EXISTS activation_chain (
                correlation_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                depth INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                PRIMARY KEY (correlation_id, agent_id)
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                timestamp REAL NOT NULL,
                correlation_id TEXT,
                agent_id TEXT,
                payload JSON NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                old_source TEXT NOT NULL,
                new_source TEXT NOT NULL,
                diff TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                file_path TEXT
            );

            CREATE TABLE IF NOT EXISTS cursor_focus (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                agent_id TEXT,
                file_path TEXT,
                line INTEGER,
                timestamp REAL
            );

            CREATE TABLE IF NOT EXISTS command_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_type TEXT NOT NULL,
                agent_id TEXT,
                payload JSON NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL,
                processed_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
            CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);
            CREATE INDEX IF NOT EXISTS idx_chain_correlation ON activation_chain(correlation_id);
        """)
        self.conn.commit()

    # ── Cursor focus ──────────────────────────────────────────────────────

    @async_db
    def update_cursor_focus(self, agent_id: str | None, file_path: str, line: int) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO cursor_focus (id, agent_id, file_path, line, timestamp)
            VALUES (1, ?, ?, ?, ?)
        """,
            (agent_id, file_path, line, time.time()),
        )
        self.conn.commit()

    def get_cursor_focus(self) -> dict | None:
        """Read the current cursor focus (sync, for web server reads)."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── LSP events ────────────────────────────────────────────────────────

    def _reconstruct_event(self, row: sqlite3.Row) -> AgentEvent:
        """Reconstruct an AgentEvent from a DB row.

        The payload column contains the full model_dump(), so subclass fields
        (to_agent, message, etc.) are preserved there as extra data accessible
        via event.payload.
        """
        stored = json.loads(row["payload"])
        # Standard fields come from indexed columns (authoritative)
        standard_keys = {"event_id", "event_type", "timestamp", "correlation_id", "agent_id", "summary", "payload"}
        extra = {k: v for k, v in stored.items() if k not in standard_keys}
        # Merge extra subclass fields into the payload dict
        inner_payload = stored.get("payload", {})
        if isinstance(inner_payload, dict):
            extra.update(inner_payload)
        return AgentEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            timestamp=row["timestamp"],
            correlation_id=row["correlation_id"],
            agent_id=row["agent_id"],
            summary=stored.get("summary", ""),
            payload=extra,
        )

    @async_db
    def get_recent_events(self, agent_id: str, limit: int = 5) -> list[AgentEvent]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events 
            WHERE agent_id = ?
               OR json_extract(payload, '$.to_agent') = ?
            ORDER BY timestamp DESC LIMIT ?
        """,
            (agent_id, agent_id, limit),
        )
        return [self._reconstruct_event(row) for row in cursor.fetchall()]

    @async_db
    def store_event(self, event: AgentEvent) -> None:
        cursor = self.conn.cursor()
        # Serialize the full model so subclass fields (to_agent, message, etc.)
        # are preserved in the payload column for later reconstruction.
        full = event.model_dump() if hasattr(event, "model_dump") else {}
        cursor.execute(
            """
            INSERT INTO events (event_id, event_type, timestamp, correlation_id, agent_id, payload)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                event.event_id,
                event.event_type,
                event.timestamp,
                event.correlation_id,
                event.agent_id,
                json.dumps(full),
            ),
        )
        self.conn.commit()

    @async_db
    def get_events_for_correlation(self, correlation_id: str) -> list[AgentEvent]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM events 
            WHERE correlation_id = ?
            ORDER BY timestamp ASC
        """,
            (correlation_id,),
        )
        return [self._reconstruct_event(row) for row in cursor.fetchall()]

    # ── Activation chain ──────────────────────────────────────────────────

    @async_db
    def add_to_chain(self, correlation_id: str, agent_id: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO activation_chain (correlation_id, agent_id, depth, timestamp)
            VALUES (?, ?, 1, ?)
        """,
            (correlation_id, agent_id, time.time()),
        )
        self.conn.commit()

    @async_db
    def get_activation_chain(self, correlation_id: str) -> list[str]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT agent_id FROM activation_chain 
            WHERE correlation_id = ?
            ORDER BY depth ASC
        """,
            (correlation_id,),
        )
        return [row["agent_id"] for row in cursor.fetchall()]

    # ── Edges ─────────────────────────────────────────────────────────────

    @async_db
    def update_edges(self, nodes: list[dict]) -> None:
        cursor = self.conn.cursor()
        for node in nodes:
            parent_id = node.get("parent_id")
            node_id = node["node_id"]
            if parent_id:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO edges (from_id, to_id, edge_type)
                    VALUES (?, ?, 'parent_of')
                """,
                    (parent_id, node_id),
                )
            for callee in node.get("callee_ids", []):
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO edges (from_id, to_id, edge_type)
                    VALUES (?, ?, 'calls')
                """,
                    (node_id, callee),
                )
        self.conn.commit()

    # ── Proposals ─────────────────────────────────────────────────────────

    @async_db
    def get_proposals_for_file(self, file_path: str) -> list[dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM proposals
            WHERE file_path = ? AND status = 'pending'
        """,
            (file_path,),
        )
        return [dict(row) for row in cursor.fetchall()]

    @async_db
    def store_proposal(
        self,
        proposal_id: str,
        agent_id: str,
        old_source: str,
        new_source: str,
        diff: str,
        file_path: str = "",
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO proposals (proposal_id, agent_id, old_source, new_source, diff, status, created_at, file_path)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
            (proposal_id, agent_id, old_source, new_source, diff, time.time(), file_path),
        )
        self.conn.commit()

    @async_db
    def update_proposal_status(self, proposal_id: str, status: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute("UPDATE proposals SET status = ? WHERE proposal_id = ?", (status, proposal_id))
        self.conn.commit()

    @async_db
    def get_proposal(self, proposal_id: str) -> dict | None:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # ── Command queue ─────────────────────────────────────────────────────

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Insert a command into the queue. Returns the command id."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO command_queue (command_type, agent_id, payload, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (command_type, agent_id, json.dumps(payload), time.time()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def poll_commands(self, limit: int = 10) -> list[dict]:
        """Read pending commands in FIFO order."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM command_queue WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_command_done(self, command_id: int) -> None:
        """Mark a command as processed."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE command_queue SET status = 'done', processed_at = ? WHERE id = ?",
            (time.time(), command_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
