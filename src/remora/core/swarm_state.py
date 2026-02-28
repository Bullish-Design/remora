"""Swarm state registry for tracking all agents."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from remora.utils import PathLike, normalize_path


@dataclass
class AgentMetadata:
    """Metadata for an agent in the swarm."""

    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    start_line: int = 1
    end_line: int = 1
    status: str = "active"
    created_at: float | None = None
    updated_at: float | None = None


class SwarmState:
    """Registry for all agents in the swarm."""

    def __init__(self, db_path: PathLike):
        self._db_path = normalize_path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database and create tables."""
        if self._conn is not None:
            return

        self._conn = await asyncio.to_thread(
            sqlite3.connect, str(self._db_path), check_same_thread=False
        )
        assert self._conn is not None
        self._conn.row_factory = sqlite3.Row

        await asyncio.to_thread(
            self._conn.execute,
            """
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                name TEXT NOT NULL,
                full_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                parent_id TEXT,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """,
        )
        await asyncio.to_thread(
            self._conn.execute,
            "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)",
        )
        await asyncio.to_thread(self._conn.commit)

    async def upsert(self, metadata: AgentMetadata) -> None:
        """Insert or update an agent."""
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None

        now = time.time()

        def _exec(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT INTO agents (agent_id, node_type, name, full_name, file_path, parent_id, start_line, end_line, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    node_type = excluded.node_type,
                    name = excluded.name,
                    full_name = excluded.full_name,
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
                    metadata.name,
                    metadata.full_name,
                    metadata.file_path,
                    metadata.parent_id,
                    metadata.start_line,
                    metadata.end_line,
                    now,
                    now,
                ),
            )

        await asyncio.to_thread(_exec, self._conn)
        await asyncio.to_thread(self._conn.commit)

    async def mark_orphaned(self, agent_id: str) -> None:
        """Mark an agent as orphaned."""
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None

        now = time.time()

        def _exec(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE agents SET status = 'orphaned', updated_at = ? WHERE agent_id = ?",
                (now, agent_id),
            )

        await asyncio.to_thread(_exec, self._conn)
        await asyncio.to_thread(self._conn.commit)

    async def list_agents(self, status: str | None = None) -> list[AgentMetadata]:
        """List all agents, optionally filtered by status."""
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None

        query = "SELECT * FROM agents"
        params: tuple[str, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)

        def _fetch(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            cursor = conn.execute(query, params)
            return cursor.fetchall()

        rows = await asyncio.to_thread(_fetch, self._conn)

        return [self._row_to_metadata(row) for row in rows]

    async def get_agent(self, agent_id: str) -> AgentMetadata | None:
        """Get a single agent by ID."""
        if self._conn is None:
            await self.initialize()
        assert self._conn is not None

        def _fetch(conn: sqlite3.Connection) -> sqlite3.Row | None:
            cursor = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ?",
                (agent_id,),
            )
            return cursor.fetchone()

        row = await asyncio.to_thread(_fetch, self._conn)

        if row is None:
            return None

        return self._row_to_metadata(row)

    async def close(self) -> None:
        """Close the database connection."""
        if not self._conn:
            return

        conn = self._conn
        self._conn = None
        await asyncio.to_thread(conn.close)

    def _row_to_metadata(self, row: sqlite3.Row) -> AgentMetadata:
        return AgentMetadata(
            agent_id=row["agent_id"],
            node_type=row["node_type"],
            name=row["name"],
            full_name=row["full_name"],
            file_path=row["file_path"],
            parent_id=row["parent_id"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


__all__ = ["AgentMetadata", "SwarmState"]
