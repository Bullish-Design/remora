"""Swarm state registry for tracking all agents."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora.utils import PathLike, normalize_path


@dataclass
class AgentMetadata:
    """Metadata for an agent in the swarm."""

    agent_id: str
    node_type: str
    file_path: str
    parent_id: str | None = None
    start_line: int = 1
    end_line: int = 1


class SwarmState:
    """Registry for all agents in the swarm."""

    def __init__(self, db_path: PathLike):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Initialize the database and create tables."""
        if self._conn is not None:
            return

        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                parent_id TEXT,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)")
        self._conn.commit()

    def upsert(self, metadata: AgentMetadata) -> None:
        """Insert or update an agent."""
        if self._conn is None:
            self.initialize()

        now = time.time()
        self._conn.execute(
            """
            INSERT INTO agents (agent_id, node_type, file_path, parent_id, start_line, end_line, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                node_type = excluded.node_type,
                file_path = excluded.file_path,
                parent_id = excluded.parent_id,
                start_line = excluded.start_line,
                end_line = excluded.end_line,
                updated_at = excluded.updated_at,
                status = 'active'
            """,
            (
                metadata.agent_id,
                metadata.node_type,
                metadata.file_path,
                metadata.parent_id,
                metadata.start_line,
                metadata.end_line,
                now,
                now,
            ),
        )
        self._conn.commit()

    def mark_orphaned(self, agent_id: str) -> None:
        """Mark an agent as orphaned."""
        if self._conn is None:
            self.initialize()

        now = time.time()
        self._conn.execute(
            "UPDATE agents SET status = 'orphaned', updated_at = ? WHERE agent_id = ?",
            (now, agent_id),
        )
        self._conn.commit()

    def list_agents(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all agents, optionally filtered by status."""
        if self._conn is None:
            self.initialize()

        query = "SELECT * FROM agents"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "agent_id": row["agent_id"],
                "node_type": row["node_type"],
                "file_path": row["file_path"],
                "parent_id": row["parent_id"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get a single agent by ID."""
        if self._conn is None:
            self.initialize()

        cursor = self._conn.execute(
            "SELECT * FROM agents WHERE agent_id = ?",
            (agent_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        return {
            "agent_id": row["agent_id"],
            "node_type": row["node_type"],
            "file_path": row["file_path"],
            "parent_id": row["parent_id"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


__all__ = ["AgentMetadata", "SwarmState"]
