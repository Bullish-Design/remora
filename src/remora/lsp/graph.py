from __future__ import annotations

import contextlib
import sqlite3
import threading
from typing import Any

import rustworkx as rx

from remora.core.store.event_store import EventStore
from remora.lsp.db import RemoraDB


class LazyGraph:
    """Graph topology backed by RemoraDB (edges) and EventStore (nodes).

    Edges live in RemoraDB. Node data is fetched via EventStore.
    """

    @staticmethod
    def _extract_node_id(node: Any) -> str | None:
        # Strict expectation: node is an AgentNode (or similar object) with a node_id attribute. No dict fallback.
        return getattr(node, "node_id", None)


    def __init__(self, db: RemoraDB, event_store: EventStore | None = None):
        # Edges connection — RemoraDB
        self._edges_conn = sqlite3.connect(str(db.db_path), check_same_thread=False)
        self._edges_conn.row_factory = sqlite3.Row

        self.event_store = event_store

        self._lock = threading.Lock()
        self.graph = rx.PyDiGraph()
        self.node_indices: dict[str, int] = {}
        self.loaded_files: set[str] = set()
        self._expanded: set[str] = set()  # nodes whose neighborhood has been loaded

    async def invalidate(self, file_path: str) -> None:
        self.loaded_files.discard(file_path)

        nodes = await self._get_nodes_for_file(file_path)
        for node in nodes:
            nid = self._extract_node_id(node)
            if not nid:
                continue
            self._expanded.discard(nid)
            if nid in self.node_indices:
                idx = self.node_indices.pop(nid)
                try:
                    self.graph.remove_node(idx)
                except Exception:
                    pass

    async def ensure_loaded(self, node_id: str) -> None:
        if node_id in self._expanded:
            return

        node = await self._get_node(node_id)
        if not node:
            return

        self._expanded.add(node_id)
        neighbors = await self._get_neighborhood(node_id, depth=2)

        for neighbor in neighbors:
            nid = self._extract_node_id(neighbor)
            if nid and nid not in self.node_indices:
                idx = self.graph.add_node(neighbor)
                self.node_indices[nid] = idx

        edges = self._get_edges_for_nodes([self._extract_node_id(n) for n in neighbors if self._extract_node_id(n)])
        for edge in edges:
            if edge["from_id"] in self.node_indices and edge["to_id"] in self.node_indices:
                self.graph.add_edge(
                    self.node_indices[edge["from_id"]], self.node_indices[edge["to_id"]], edge["edge_type"]
                )

    async def get_parent(self, node_id: str) -> str | None:
        await self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return None

        idx = self.node_indices[node_id]
        for predecessor in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(predecessor, idx)
            if edge == "parent_of":
                data = self.graph.get_node_data(predecessor)
                return self._extract_node_id(data)

        return None

    async def get_callers(self, node_id: str) -> list[str]:
        await self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return []

        idx = self.node_indices[node_id]
        callers = []
        for predecessor in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(predecessor, idx)
            if edge == "calls":
                data = self.graph.get_node_data(predecessor)
                nid = self._extract_node_id(data)
                if nid:
                    callers.append(nid)

        return callers

    def close(self) -> None:
        self._edges_conn.close()

    def __del__(self) -> None:
        # Finalizer safeguard for tests that forget explicit shutdown.
        try:
            self.close()
        except Exception:
            pass

    # ── Private: node queries (EventStore DB) ─────────────────────────────

    async def _get_nodes_for_file(self, file_path: str) -> list[Any]:
        if not self.event_store:
            return []
        return await self.event_store.nodes.list_nodes(file_path=file_path)

    async def _get_node(self, node_id: str) -> Any | None:
        if not self.event_store:
            return None
        return await self.event_store.nodes.get_node(node_id)

    async def _get_neighborhood(self, node_id: str, depth: int = 2) -> list[Any]:
        """Get node + neighbors by walking edges, then fetching node data."""
        with self._lock:
            # Walk edges to find neighbor IDs
            with contextlib.closing(self._edges_conn.execute(
                """
                WITH RECURSIVE neighbors(nid, d) AS (
                    SELECT ?, 0
                    UNION ALL
                    SELECT CASE
                        WHEN e.from_id = n.nid THEN e.to_id
                        ELSE e.from_id
                    END, n.d + 1
                    FROM edges e
                    JOIN neighbors n ON e.from_id = n.nid OR e.to_id = n.nid
                    WHERE n.d < ?
                )
                SELECT DISTINCT nid FROM neighbors
            """,
                (node_id, depth),
            )) as cursor:
                neighbor_ids = [row[0] for row in cursor.fetchall()]

        if not neighbor_ids or not self.event_store:
            return []

        # Fetch node data from EventStore
        nodes = []
        for nid in neighbor_ids:
            node = await self._get_node(nid)
            if node:
                nodes.append(node)
        return nodes

    # ── Private: edge queries (RemoraDB) ──────────────────────────────────

    def _get_edges_for_nodes(self, node_ids: list[str]) -> list[dict]:
        if not node_ids:
            return []

        placeholders = ",".join("?" * len(node_ids))
        params = node_ids + node_ids
        with self._lock:
            with contextlib.closing(self._edges_conn.execute(
                f"""
                SELECT * FROM edges 
                WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})
            """,
                params,
            )) as cursor:
                return [dict(row) for row in cursor.fetchall()]

