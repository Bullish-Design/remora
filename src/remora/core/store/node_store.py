"""Read model for tracking AgentNodes in the workspace."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import uuid
from typing import Any

import remora.core.store.event_store_queries as store_queries
from remora.core.agents.agent_node import AgentNode


CODE_NODE_KINDS: frozenset[str] = frozenset(
    {
        "function",
        "class",
        "method",
        "file",
        "section",
        "table",
        "note",
        "todo",
    }
)
MODULE_KIND_ALIAS = "module"


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _agent_node_to_graph_dict(node: AgentNode, *, kind_override: str | None = None) -> dict[str, Any]:
    return {
        "id": node.node_id,
        "kind": kind_override or node.node_type,
        "attrs": {
            "name": node.name,
            "full_name": node.full_name,
            "file_path": node.file_path,
            "start_line": node.start_line,
            "end_line": node.end_line,
            "status": node.status,
        },
    }


class NodeStore:
    """Read-optimized store for querying current code node state.

    This isolates the 'nodes' projection table from the main append-only
    EventStore, reducing coupling and god-object scope.
    """

    def __init__(
        self,
        read_conn: sqlite3.Connection,
        read_lock: asyncio.Lock,
        write_conn: sqlite3.Connection | None = None,
        write_lock: asyncio.Lock | None = None,
    ):
        """Initialize the NodeStore with read access to the database.

        Args:
            read_conn: A dedicated read-only SQLite connection.
            read_lock: An asyncio.Lock that serializes concurrent to_thread
                       accesses against the read connection.
        """
        self._read_conn = read_conn
        self._read_lock = read_lock
        self._write_conn = write_conn
        self._write_lock = write_lock

    def bind_write_backend(self, conn: sqlite3.Connection, lock: asyncio.Lock) -> None:
        """Attach write connection/lock for node mutations."""
        self._write_conn = conn
        self._write_lock = lock

    def bind_read_lock(self, lock: asyncio.Lock) -> None:
        """Attach read lock for node queries."""
        self._read_lock = lock

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

    async def set_node_status(self, node_id: str, status: str) -> None:
        """Update the status field of a node directly.

        Requires a bound write backend.
        """
        if self._write_conn is None or self._write_lock is None:
            raise RuntimeError("NodeStore write backend is not initialized")

        async with self._write_lock:
            await asyncio.to_thread(
                store_queries.update_node_status,
                self._write_conn,
                node_id=node_id,
                status=status,
            )

    async def remove_nodes_for_file(self, file_path: str) -> int:
        """Remove all nodes for a given file path. Returns count removed.

        Requires a bound write backend.
        """
        if self._write_conn is None or self._write_lock is None:
            raise RuntimeError("NodeStore write backend is not initialized")

        async with self._write_lock:
            return await asyncio.to_thread(
                store_queries.delete_nodes_for_file,
                self._write_conn,
                file_path=file_path,
            )

    async def read_graph(self, selector: dict[str, Any]) -> str:
        """Read from the unified graph surface.

        Supported selectors:
        - {"node": "<node_id>"}
        - {"neighbors": "<node_id>", "dir": "in|out|both"}
        - {"match": {"kind": "<kind>", ...attr_filters}}
        """
        if "node" in selector:
            node_id = str(selector["node"])
            return await self._graph_get_node(node_id)
        if "neighbors" in selector:
            node_id = str(selector["neighbors"])
            direction = str(selector.get("dir", "both"))
            return await self._graph_get_neighbors(node_id, direction)
        if "match" in selector:
            match = selector["match"]
            if not isinstance(match, dict):
                raise ValueError("Graph match selector must be a dictionary")
            return await self._graph_find_nodes(match)
        raise ValueError(f"Unknown graph read selector: {selector!r}")

    async def write_graph(self, op: str, data: dict[str, Any]) -> str:
        """Write to the generic graph surface."""
        if op == "add_node":
            return await self._graph_add_node(data)
        if op == "add_edge":
            return await self._graph_add_edge(data)
        raise ValueError(f"Unknown graph write op: {op!r}")

    async def _graph_get_node(self, node_id: str) -> str:
        node = await self.get_node(node_id)
        if node is not None:
            return json.dumps(_agent_node_to_graph_dict(node))

        def _fetch(conn: sqlite3.Connection) -> dict[str, Any] | None:
            with contextlib.closing(
                conn.execute(
                    "SELECT id, kind, attrs_json FROM graph_nodes WHERE id = ?",
                    (node_id,),
                )
            ) as cursor:
                row = cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "kind": row["kind"],
                "attrs": _safe_json_loads(row["attrs_json"]),
            }

        async with self._read_lock:
            result = await asyncio.to_thread(_fetch, self._read_conn)
        return json.dumps(result)

    async def _graph_find_nodes(self, match: dict[str, Any]) -> str:
        kind_raw = match.get("kind")
        kind = str(kind_raw) if kind_raw is not None else None
        filters = {k: v for k, v in match.items() if k != "kind"}

        if kind in CODE_NODE_KINDS or kind == MODULE_KIND_ALIAS:
            query_kind = "file" if kind == MODULE_KIND_ALIAS else kind
            nodes = await self.list_nodes(node_type=query_kind)
            projected = [
                _agent_node_to_graph_dict(node, kind_override=MODULE_KIND_ALIAS if kind == MODULE_KIND_ALIAS else None)
                for node in nodes
            ]
            filtered = [
                row
                for row in projected
                if all(row["attrs"].get(attr) == value for attr, value in filters.items())
            ]
            if kind != MODULE_KIND_ALIAS:
                return json.dumps(filtered)
            # Compatibility: include previously-seeded generic "module" rows too.
            generic_rows = await self._graph_fetch_generic_nodes(kind=MODULE_KIND_ALIAS, filters=filters)
            merged: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for row in filtered + generic_rows:
                row_id = str(row.get("id", ""))
                if row_id and row_id not in seen_ids:
                    seen_ids.add(row_id)
                    merged.append(row)
            return json.dumps(merged)

        rows = await self._graph_fetch_generic_nodes(kind=kind, filters=filters)
        return json.dumps(rows)

    async def _graph_fetch_generic_nodes(self, *, kind: str | None, filters: dict[str, Any]) -> list[dict[str, Any]]:
        def _fetch(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            if kind:
                with contextlib.closing(
                    conn.execute(
                        "SELECT id, kind, attrs_json FROM graph_nodes WHERE kind = ?",
                        (kind,),
                    )
                ) as cursor:
                    rows = cursor.fetchall()
            else:
                with contextlib.closing(conn.execute("SELECT id, kind, attrs_json FROM graph_nodes")) as cursor:
                    rows = cursor.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                attrs = _safe_json_loads(row["attrs_json"])
                if all(attrs.get(attr) == value for attr, value in filters.items()):
                    result.append({"id": row["id"], "kind": row["kind"], "attrs": attrs})
            return result

        async with self._read_lock:
            return await asyncio.to_thread(_fetch, self._read_conn)

    async def _graph_get_neighbors(self, node_id: str, direction: str) -> str:
        if direction not in {"in", "out", "both"}:
            raise ValueError(f"Unsupported neighbor direction: {direction!r}")

        code_node = await self.get_node(node_id)
        if code_node is not None:
            if direction == "in":
                neighbor_ids = list(code_node.caller_ids)
            elif direction == "out":
                neighbor_ids = list(code_node.callee_ids)
            else:
                neighbor_ids = list(dict.fromkeys([*code_node.caller_ids, *code_node.callee_ids]))

            neighbors: list[dict[str, Any]] = []
            for neighbor_id in neighbor_ids:
                raw = await self._graph_get_node(neighbor_id)
                parsed = json.loads(raw)
                if parsed:
                    parsed["edge_kind"] = "calls"
                    neighbors.append(parsed)
            return json.dumps(neighbors)

        def _fetch(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            if direction == "out":
                query = """
                    SELECT n.id, n.kind, n.attrs_json, e.kind AS edge_kind
                    FROM graph_edges e
                    JOIN graph_nodes n ON e.to_id = n.id
                    WHERE e.from_id = ?
                """
                params = (node_id,)
            elif direction == "in":
                query = """
                    SELECT n.id, n.kind, n.attrs_json, e.kind AS edge_kind
                    FROM graph_edges e
                    JOIN graph_nodes n ON e.from_id = n.id
                    WHERE e.to_id = ?
                """
                params = (node_id,)
            else:
                query = """
                    SELECT n.id, n.kind, n.attrs_json, e.kind AS edge_kind
                    FROM graph_edges e
                    JOIN graph_nodes n ON (e.to_id = n.id AND e.from_id = ?)
                    UNION ALL
                    SELECT n.id, n.kind, n.attrs_json, e.kind AS edge_kind
                    FROM graph_edges e
                    JOIN graph_nodes n ON (e.from_id = n.id AND e.to_id = ?)
                """
                params = (node_id, node_id)

            with contextlib.closing(conn.execute(query, params)) as cursor:
                rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "attrs": _safe_json_loads(row["attrs_json"]),
                    "edge_kind": row["edge_kind"],
                }
                for row in rows
            ]

        async with self._read_lock:
            result = await asyncio.to_thread(_fetch, self._read_conn)
        return json.dumps(result)

    async def _graph_add_node(self, data: dict[str, Any]) -> str:
        write_conn, write_lock = self._write_backend()
        kind = str(data["kind"])
        if kind in CODE_NODE_KINDS or kind == MODULE_KIND_ALIAS:
            raise ValueError(f"Cannot write code node kind through graph API: {kind}")

        attrs = data.get("attrs") or {}
        if not isinstance(attrs, dict):
            raise ValueError("add_node attrs must be a dictionary")

        node_id = str(data.get("id") or uuid.uuid4())
        attrs_json = json.dumps(attrs)

        def _exec(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT OR REPLACE INTO graph_nodes (id, kind, attrs_json) VALUES (?, ?, ?)",
                (node_id, kind, attrs_json),
            )

        async with write_lock:
            await asyncio.to_thread(_exec, write_conn)
        return json.dumps({"id": node_id, "kind": kind})

    async def _graph_add_edge(self, data: dict[str, Any]) -> str:
        write_conn, write_lock = self._write_backend()

        from_id = str(data["from"])
        to_id = str(data["to"])
        kind = str(data["kind"])

        attrs = data.get("attrs") or {}
        if not isinstance(attrs, dict):
            raise ValueError("add_edge attrs must be a dictionary")
        attrs_json = json.dumps(attrs)

        def _exec(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                INSERT OR REPLACE INTO graph_edges (from_id, to_id, kind, attrs_json)
                VALUES (?, ?, ?, ?)
                """,
                (from_id, to_id, kind, attrs_json),
            )

        async with write_lock:
            await asyncio.to_thread(_exec, write_conn)
        return json.dumps({"from": from_id, "to": to_id, "kind": kind})

    def _write_backend(self) -> tuple[sqlite3.Connection, asyncio.Lock]:
        if self._write_conn is None or self._write_lock is None:
            raise RuntimeError("NodeStore write backend is not initialized")
        return self._write_conn, self._write_lock


__all__ = ["CODE_NODE_KINDS", "NodeStore"]
