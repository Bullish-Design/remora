from __future__ import annotations

import sqlite3
import threading

try:
    import rustworkx as rx

    RUSTWORKX_AVAILABLE = True
except ImportError:
    RUSTWORKX_AVAILABLE = False

from remora.lsp.db import RemoraDB


class LazyGraph:
    def __init__(self, db: RemoraDB):
        self._conn = sqlite3.connect(str(db.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.graph = rx.PyDiGraph() if RUSTWORKX_AVAILABLE else None
        self.node_indices: dict[str, int] = {}
        self.loaded_files: set[str] = set()

    def invalidate(self, file_path: str) -> None:
        self.loaded_files.discard(file_path)
        if not RUSTWORKX_AVAILABLE or not self.graph:
            return

        nodes = self._get_nodes_for_file(file_path)
        for node in nodes:
            if node["id"] in self.node_indices:
                idx = self.node_indices.pop(node["id"])
                try:
                    self.graph.remove_node(idx)
                except Exception:
                    pass

    def ensure_loaded(self, node_id: str) -> None:
        if not RUSTWORKX_AVAILABLE or not self.graph:
            return

        if node_id in self.node_indices:
            return

        node = self._get_node(node_id)
        if not node:
            return

        neighbors = self._get_neighborhood(node_id, depth=2)

        for neighbor in neighbors:
            if neighbor["id"] not in self.node_indices:
                idx = self.graph.add_node(neighbor)
                self.node_indices[neighbor["id"]] = idx

        edges = self._get_edges_for_nodes([n["id"] for n in neighbors])
        for edge in edges:
            if edge["from_id"] in self.node_indices and edge["to_id"] in self.node_indices:
                self.graph.add_edge(
                    self.node_indices[edge["from_id"]], self.node_indices[edge["to_id"]], edge["edge_type"]
                )

    def get_parent(self, node_id: str) -> str | None:
        if not RUSTWORKX_AVAILABLE or not self.graph:
            return None

        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return None

        idx = self.node_indices[node_id]
        for predecessor in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(predecessor, idx)
            if edge == "parent_of":
                return self.graph[predecessor]["id"]

        return None

    def get_callers(self, node_id: str) -> list[str]:
        if not RUSTWORKX_AVAILABLE or not self.graph:
            return []

        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return []

        idx = self.node_indices[node_id]
        callers = []
        for predecessor in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(predecessor, idx)
            if edge == "calls":
                callers.append(self.graph[predecessor]["id"])

        return callers

    def close(self) -> None:
        self._conn.close()

    def _get_nodes_for_file(self, file_path: str) -> list[dict]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM nodes WHERE file_path = ?", (file_path,))
            return [dict(row) for row in cursor.fetchall()]

    def _get_node(self, node_id: str) -> dict | None:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def _get_neighborhood(self, node_id: str, depth: int = 2) -> list[dict]:
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                WITH RECURSIVE neighbors(from_id, to_id, edge_type, d) AS (
                    SELECT NULL, ?, 'self', 0
                    UNION ALL
                    SELECT e.from_id, e.to_id, e.edge_type, n.d + 1
                    FROM edges e
                    JOIN neighbors n ON e.from_id = n.to_id OR e.to_id = n.from_id
                    WHERE n.d < ?
                )
                SELECT DISTINCT id FROM nodes
                WHERE id IN (SELECT from_id FROM neighbors) OR id IN (SELECT to_id FROM neighbors)
            """,
                (node_id, depth),
            )
            node_ids = [row["id"] for row in cursor.fetchall()]

            if not node_ids:
                return []

            placeholders = ",".join("?" * len(node_ids))
            cursor.execute(f"SELECT * FROM nodes WHERE id IN ({placeholders})", node_ids)
            return [dict(row) for row in cursor.fetchall()]

    def _get_edges_for_nodes(self, node_ids: list[str]) -> list[dict]:
        if not node_ids:
            return []

        placeholders = ",".join("?" * len(node_ids))
        params = node_ids + node_ids
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                f"""
                SELECT * FROM edges 
                WHERE from_id IN ({placeholders}) AND to_id IN ({placeholders})
            """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]
