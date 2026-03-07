"""Read model for tracking AgentNodes in the workspace."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3

import remora.core.store.event_store_queries as store_queries
from remora.core.agents.agent_node import AgentNode


class NodeStore:
    """Read-optimized store for querying current code node state.

    This isolates the 'nodes' projection table from the main append-only
    EventStore, reducing coupling and god-object scope.
    """

    def __init__(self, read_conn: sqlite3.Connection, read_lock: asyncio.Lock):
        """Initialize the NodeStore with read access to the database.

        Args:
            read_conn: A dedicated read-only SQLite connection.
            read_lock: An asyncio.Lock that serializes concurrent to_thread
                       accesses against the read connection.
        """
        self._read_conn = read_conn
        self._read_lock = read_lock

    async def get_node(self, node_id: str) -> AgentNode | None:
        """Get a single AgentNode by ID from the nodes table."""
        async with self._read_lock:
            row = await asyncio.to_thread(
                store_queries.fetch_node_row,
                self._read_conn,
                node_id=node_id,
            )

        if row is None:
            return None
        return AgentNode.from_row(row)

    async def list_nodes(
        self,
        *,
        file_path: str | None = None,
        node_type: str | None = None,
        columns: list[str] | None = None,
    ) -> list[AgentNode]:
        """List AgentNodes with optional filters.

        Args:
            file_path: Filter by file path.
            node_type: Filter by node type.
            columns: If provided, only SELECT these columns (optimization to
                     avoid fetching large source_code blobs).  When *columns*
                     is ``None`` (the default), ``SELECT *`` is used and full
                     ``AgentNode`` objects are returned.
        """
        async with self._read_lock:
            rows = await asyncio.to_thread(
                store_queries.fetch_node_rows,
                self._read_conn,
                file_path=file_path,
                node_type=node_type,
                columns=columns,
            )

        return [AgentNode.from_row(row) for row in rows]

    async def get_node_at_position(
        self,
        file_path: str,
        line: int,
    ) -> AgentNode | None:
        """Get the narrowest AgentNode containing the given line in a file."""
        async with self._read_lock:
            row = await asyncio.to_thread(
                store_queries.fetch_node_at_position_row,
                self._read_conn,
                file_path=file_path,
                line=line,
            )

        if row is None:
            return None
        return AgentNode.from_row(row)

    async def set_node_status(self, conn: sqlite3.Connection, lock: asyncio.Lock, node_id: str, status: str) -> None:
        """Update the status field of a node directly.
        
        Note: This is a mutation, so it requires the write connection and lock
        passed from the EventStore orchestrator or running within a unit of work.
        """
        async with lock:
            await asyncio.to_thread(
                store_queries.update_node_status,
                conn,
                node_id=node_id,
                status=status,
            )

    async def remove_nodes_for_file(self, conn: sqlite3.Connection, lock: asyncio.Lock, file_path: str) -> int:
        """Remove all nodes for a given file path. Returns count removed.
        
        Note: This is a mutation, so it requires the write connection and lock.
        """
        async with lock:
            return await asyncio.to_thread(
                store_queries.delete_nodes_for_file,
                conn,
                file_path=file_path,
            )


__all__ = ["NodeStore"]
