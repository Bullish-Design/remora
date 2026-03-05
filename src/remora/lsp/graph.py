from __future__ import annotations

import sqlite3
import threading

import rustworkx as rx

from remora.lsp.db import RemoraDB


class LazyGraph:
    """Graph topology backed by RemoraDB (edges) and EventStore (nodes).

    Edges live in RemoraDB. Node data lives in EventStore's nodes table.
    Each source has its own SQLite connection for thread-safe reads.
    """

    def __init__(self, db: RemoraDB, event_store_db_path: str | None = None):
        # Edges connection — RemoraDB
        self._edges_conn = sqlite3.connect(str(db.db_path), check_same_thread=False)
        self._edges_conn.row_factory = sqlite3.Row

        # Nodes connection — EventStore DB (if available)
        self._nodes_conn: sqlite3.Connection | None = None
        if event_store_db_path:
            self._nodes_conn = sqlite3.connect(
                event_store_db_path,
                timeout=15.0,
                check_same_thread=False,
                isolation_level=None,
            )
            self._nodes_conn.execute("PRAGMA journal_mode=WAL")
            self._nodes_conn.row_factory = sqlite3.Row

        self._lock = threading.Lock()
        self.graph = rx.PyDiGraph()
        self.node_indices: dict[str, int] = {}
        self.loaded_files: set[str] = set()
        self._expanded: set[str] = set()  # nodes whose neighborhood has been loaded

    def invalidate(self, file_path: str) -> None:
        self.loaded_files.discard(file_path)

        nodes = self._get_nodes_for_file(file_path)
        for node in nodes:
            nid = node.get("id", node.get("node_id"))
            self._expanded.discard(nid)
            if nid in self.node_indices:
                idx = self.node_indices.pop(nid)
                try:
                    self.graph.remove_node(idx)
                except Exception:
                    pass

    def ensure_loaded(self, node_id: str) -> None:
        if node_id in self._expanded:
            return

        node = self._get_node(node_id)
        if not node:
            return

        self._expanded.add(node_id)
        neighbors = self._get_neighborhood(node_id, depth=2)

        for neighbor in neighbors:
            nid = neighbor.get("id", neighbor.get("node_id"))
            if nid not in self.node_indices:
                idx = self.graph.add_node(neighbor)
                self.node_indices[nid] = idx

        edges = self._get_edges_for_nodes([n.get("id", n.get("node_id")) for n in neighbors])
        for edge in edges:
            if edge["from_id"] in self.node_indices and edge["to_id"] in self.node_indices:
                self.graph.add_edge(
                    self.node_indices[edge["from_id"]], self.node_indices[edge["to_id"]], edge["edge_type"]
                )

    def get_parent(self, node_id: str) -> str | None:
        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return None

        idx = self.node_indices[node_id]
        for predecessor in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(predecessor, idx)
            if edge == "parent_of":
                data = self.graph[predecessor]
                return data.get("id", data.get("node_id"))

        return None

    def get_callers(self, node_id: str) -> list[str]:
        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return []

        idx = self.node_indices[node_id]
        callers = []
        for predecessor in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(predecessor, idx)
            if edge == "calls":
                data = self.graph[predecessor]
                callers.append(data.get("id", data.get("node_id")))

        return callers

    def close(self) -> None:
        self._edges_conn.close()
        if self._nodes_conn:
            self._nodes_conn.close()

    # ── Private: node queries (EventStore DB) ─────────────────────────────

    def _get_nodes_for_file(self, file_path: str) -> list[dict]:
        if not self._nodes_conn:
            return []
        with self._lock:
            cursor = self._nodes_conn.cursor()
            cursor.execute("SELECT * FROM nodes WHERE file_path = ?", (file_path,))
            return [self._normalize_node(row) for row in cursor.fetchall()]

    def _get_node(self, node_id: str) -> dict | None:
        if not self._nodes_conn:
            return None
        with self._lock:
            cursor = self._nodes_conn.cursor()
            cursor.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            row = cursor.fetchone()
        return self._normalize_node(row) if row else None

    def _get_neighborhood(self, node_id: str, depth: int = 2) -> list[dict]:
        """Get node + neighbors by walking edges, then fetching node data."""
        with self._lock:
            # Walk edges to find neighbor IDs
            cursor = self._edges_conn.cursor()
            cursor.execute(
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
            )
            neighbor_ids = [row[0] for row in cursor.fetchall()]

        if not neighbor_ids or not self._nodes_conn:
            return []

        # Fetch node data from EventStore DB
        with self._lock:
            placeholders = ",".join("?" * len(neighbor_ids))
            cursor = self._nodes_conn.cursor()
            cursor.execute(f"SELECT * FROM nodes WHERE node_id IN ({placeholders})", neighbor_ids)
            return [self._normalize_node(row) for row in cursor.fetchall()]

    # ── Private: edge queries (RemoraDB) ──────────────────────────────────

    def _get_edges_for_nodes(self, node_ids: list[str]) -> list[dict]:
        if not node_ids:
            return []

        placeholders = ",".join("?" * len(node_ids))
        params = node_ids + node_ids
        with self._lock:
            cursor = self._edges_conn.cursor()
            cursor.execute(
                f"""
                SELECT * FROM edges 
                WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})
            """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _normalize_node(row: sqlite3.Row) -> dict:
        """Ensure node dict has both 'id' and 'node_id' keys for compat."""
        data = dict(row)
        if "node_id" in data and "id" not in data:
            data["id"] = data["node_id"]
        return data
