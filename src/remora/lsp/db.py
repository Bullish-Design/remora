# src/remora/lsp/db.py
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import ParamSpec, TypeVar

from remora.core.code.discovery import CSTNode

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
    """LSP-specific database for proposals, edges, cursor focus, and commands.

    Node state lives in EventStore (core). Event storage also lives in EventStore.
    This DB holds LSP-specific operational state that doesn't belong in the
    event-sourced core.

    Can operate in two modes:
    - **Standalone**: pass ``db_path`` and the DB opens its own SQLite
      connection and creates tables.
    - **Shared**: pass ``connection`` and ``lock`` from an ``EventStore``
      instance.  Tables are assumed to already exist (created by
      ``EventStore.initialize()``).
    """

    def __init__(
        self,
        db_path: str = ".remora/indexer.db",
        *,
        connection: sqlite3.Connection | None = None,
        lock: object | None = None,
    ):
        if connection is not None:
            # Shared-connection mode — tables already created by EventStore
            self.db_path: Path | None = None
            self.conn = connection
            self.conn.row_factory = sqlite3.Row
            self._lock = lock if lock is not None else threading.Lock()
            self._shared = True
            self._init_schema()  # Always create LSP tables — idempotent with IF NOT EXISTS
        else:
            # Standalone mode (backward compat)
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.db_path), timeout=15.0, check_same_thread=False, isolation_level=None)
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.row_factory = sqlite3.Row
            self._lock = threading.Lock()
            self._shared = False
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

            CREATE INDEX IF NOT EXISTS idx_chain_correlation ON activation_chain(correlation_id);
        """)
        self._migrate()

    def _migrate(self):
        """Add columns that may be missing from older databases."""
        with contextlib.closing(self.conn.execute("PRAGMA table_info(proposals)")) as cursor:
            columns = {row[1] for row in cursor.fetchall()}
        if "file_path" not in columns:
            with contextlib.closing(self.conn.cursor()) as cursor:
                cursor.execute("ALTER TABLE proposals ADD COLUMN file_path TEXT")

    # ── Cursor focus ──────────────────────────────────────────────────────

    @async_db
    def update_cursor_focus(self, agent_id: str | None, file_path: str, line: int) -> None:
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO cursor_focus (id, agent_id, file_path, line, timestamp)
                VALUES (1, ?, ?, ?, ?)
            """,
                (agent_id, file_path, line, time.time()),
            )

    def get_cursor_focus(self) -> dict | None:
        """Read the current cursor focus (sync, for web server reads)."""
        with contextlib.closing(self.conn.execute("SELECT agent_id, file_path, line, timestamp FROM cursor_focus WHERE id = 1")) as cursor:
            row = cursor.fetchone()
        return dict(row) if row else None

    # ── Activation chain ──────────────────────────────────────────────────

    @async_db
    def add_to_chain(self, correlation_id: str, agent_id: str) -> None:
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute(
                """
                INSERT OR REPLACE INTO activation_chain (correlation_id, agent_id, depth, timestamp)
                VALUES (?, ?, 1, ?)
            """,
                (correlation_id, agent_id, time.time()),
            )

    @async_db
    def get_activation_chain(self, correlation_id: str) -> list[str]:
        with contextlib.closing(self.conn.execute(
            """
            SELECT agent_id FROM activation_chain 
            WHERE correlation_id = ?
            ORDER BY depth ASC
        """,
            (correlation_id,),
        )) as cursor:
            return [row["agent_id"] for row in cursor.fetchall()]

    # ── Edges ─────────────────────────────────────────────────────────────

    @async_db
    def update_edges(self, nodes: list[CSTNode]) -> None:
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute("BEGIN IMMEDIATE")
            try:
                for node in nodes:
                    if node.parent_id:
                        cursor.execute(
                            "INSERT OR REPLACE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'parent_of')",
                            (node.parent_id, node.node_id),
                        )
                cursor.execute("COMMIT")
            except Exception:
                cursor.execute("ROLLBACK")
                raise

    # ── Proposals ─────────────────────────────────────────────────────────

    @async_db
    def get_proposals_for_file(self, file_path: str) -> list[dict]:
        with contextlib.closing(self.conn.execute(
            """
            SELECT * FROM proposals
            WHERE file_path = ? AND status = 'pending'
        """,
            (file_path,),
        )) as cursor:
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
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute(
                """
                INSERT INTO proposals (proposal_id, agent_id, old_source, new_source, diff, status, created_at, file_path)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
                (proposal_id, agent_id, old_source, new_source, diff, time.time(), file_path),
            )

    @async_db
    def update_proposal_status(self, proposal_id: str, status: str) -> None:
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute("UPDATE proposals SET status = ? WHERE proposal_id = ?", (status, proposal_id))

    @async_db
    def get_proposal(self, proposal_id: str) -> dict | None:
        with contextlib.closing(self.conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,))) as cursor:
            row = cursor.fetchone()
        return dict(row) if row else None

    # ── Command queue ─────────────────────────────────────────────────────

    def push_command(self, command_type: str, agent_id: str | None, payload: dict) -> int:
        """Insert a command into the queue. Returns the command id."""
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute(
                """
                INSERT INTO command_queue (command_type, agent_id, payload, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (command_type, agent_id, json.dumps(payload), time.time()),
            )
            return cursor.lastrowid

    def poll_commands(self, limit: int = 10) -> list[dict]:
        """Read pending commands in FIFO order."""
        with contextlib.closing(self.conn.execute(
            "SELECT * FROM command_queue WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        )) as cursor:
            return [dict(row) for row in cursor.fetchall()]

    def mark_command_done(self, command_id: int) -> None:
        """Mark a command as processed."""
        with contextlib.closing(self.conn.cursor()) as cursor:
            cursor.execute(
                "UPDATE command_queue SET status = 'done', processed_at = ? WHERE id = ?",
                (time.time(), command_id),
            )

    def close(self) -> None:
        if self._shared:
            # Don't close shared connection — it's owned by EventStore
            return
        self.conn.close()

    def __del__(self) -> None:
        # Finalizer safeguard for tests that forget explicit shutdown.
        try:
            self.close()
        except Exception:
            pass
