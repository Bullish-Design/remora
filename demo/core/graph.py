try:
    import rustworkx as rx

    RUSTWORKX_AVAILABLE = True
except ImportError:
    RUSTWORKX_AVAILABLE = False

from .db import RemoraDB
from .models import ASTAgentNode


class LazyGraph:
    def __init__(self, db: RemoraDB):
        self.db = db
        self.graph = rx.PyDiGraph() if RUSTWORKX_AVAILABLE else None
        self.node_indices: dict[str, int] = {}
        self.loaded_files: set[str] = set()

    def invalidate(self, file_path: str):
        self.loaded_files.discard(file_path)
        if RUSTWORKX_AVAILABLE and self.graph:
            nodes = self.db.get_nodes_for_file(file_path)
            for node in nodes:
                if node["id"] in self.node_indices:
                    idx = self.node_indices.pop(node["id"])
                    try:
                        self.graph.remove_node(idx)
                    except:
                        pass

    def ensure_loaded(self, node_id: str):
        if not RUSTWORKX_AVAILABLE:
            return

        if node_id in self.node_indices:
            return

        node = self.db.get_node(node_id)
        if not node:
            return

        neighbors = self.db.get_neighborhood(node_id, depth=2)

        for n in neighbors:
            if n["id"] not in self.node_indices:
                idx = self.graph.add_node(n)
                self.node_indices[n["id"]] = idx

        edges = self.db.get_edges_for_nodes([n["id"] for n in neighbors])
        for edge in edges:
            if edge["from_id"] in self.node_indices and edge["to_id"] in self.node_indices:
                self.graph.add_edge(
                    self.node_indices[edge["from_id"]], self.node_indices[edge["to_id"]], edge["edge_type"]
                )

    def get_parent(self, node_id: str) -> str | None:
        if not RUSTWORKX_AVAILABLE:
            return None

        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return None

        idx = self.node_indices[node_id]
        parents = self.graph.predecessor_indices(idx)

        for p_idx in parents:
            edge = self.graph.get_edge_data(p_idx, idx)
            if edge == "parent_of":
                return self.graph[p_idx]["id"]

        return None

    def get_callers(self, node_id: str) -> list[str]:
        if not RUSTWORKX_AVAILABLE:
            return []

        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return []

        idx = self.node_indices[node_id]
        callers = []

        for p_idx in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(p_idx, idx)
            if edge == "calls":
                callers.append(self.graph[p_idx]["id"])

        return callers
