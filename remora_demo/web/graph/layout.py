"""Server-side force-directed graph layout."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class LayoutNode:
    id: str
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    node_type: str = "function"
    pinned: bool = False


@dataclass
class LayoutEdge:
    source: str
    target: str
    edge_type: str = "calls"


class ForceLayout:
    """Minimal force-directed layout for small graphs (<50 nodes).

    Forces:
    - Repulsion: all pairs, inverse-square
    - Attraction: linked pairs, spring
    - Center gravity: pulls everything toward center
    - Hierarchy: file nodes float up, children below
    """

    def __init__(
        self,
        width: float = 900,
        height: float = 600,
        repulsion: float = 5000.0,
        attraction: float = 0.005,
        gravity: float = 0.02,
        damping: float = 0.9,
    ) -> None:
        self.width = width
        self.height = height
        self.repulsion = repulsion
        self.attraction = attraction
        self.gravity = gravity
        self.damping = damping
        self.nodes: dict[str, LayoutNode] = {}
        self.edges: list[LayoutEdge] = []

    def set_graph(self, nodes: list[dict], edges: list[dict]) -> None:
        """Set the full graph. Preserves positions for existing nodes."""
        existing = {n.id: n for n in self.nodes.values()}
        self.nodes = {}
        for n in nodes:
            nid = n.get("remora_id") or n.get("id", "")
            if nid in existing:
                self.nodes[nid] = existing[nid]
                # Update metadata
                self.nodes[nid].node_type = n.get("node_type", "function")
            else:
                # Seed position: files at top, functions below
                nt = n.get("node_type", "function")
                y_seed = 100 if nt == "file" else 300 + random.uniform(-50, 50)
                x_seed = self.width / 2 + random.uniform(-200, 200)
                self.nodes[nid] = LayoutNode(
                    id=nid,
                    x=x_seed,
                    y=y_seed,
                    node_type=nt,
                )

        self.edges = [
            LayoutEdge(
                source=e.get("from_id", ""),
                target=e.get("to_id", ""),
                edge_type=e.get("edge_type", "calls"),
            )
            for e in edges
        ]

    def step(self, iterations: int = 1) -> None:
        """Run N iterations of the force simulation."""
        node_list = list(self.nodes.values())
        n = len(node_list)
        if n == 0:
            return

        cx, cy = self.width / 2, self.height / 2

        for _ in range(iterations):
            # Repulsion (all pairs)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = node_list[i], node_list[j]
                    dx = a.x - b.x
                    dy = a.y - b.y
                    dist_sq = dx * dx + dy * dy + 1.0
                    force = self.repulsion / dist_sq
                    dist = math.sqrt(dist_sq)
                    fx = force * dx / dist
                    fy = force * dy / dist
                    if not a.pinned:
                        a.vx += fx
                        a.vy += fy
                    if not b.pinned:
                        b.vx -= fx
                        b.vy -= fy

            # Attraction (linked pairs)
            for edge in self.edges:
                a = self.nodes.get(edge.source)
                b = self.nodes.get(edge.target)
                if not a or not b:
                    continue
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.sqrt(dx * dx + dy * dy + 1.0)
                # Shorter desired distance for parent_of edges
                desired = 80 if edge.edge_type == "parent_of" else 160
                force = self.attraction * (dist - desired)
                fx = force * dx / dist
                fy = force * dy / dist
                if not a.pinned:
                    a.vx += fx
                    a.vy += fy
                if not b.pinned:
                    b.vx -= fx
                    b.vy -= fy

            # Center gravity
            for node in node_list:
                if not node.pinned:
                    node.vx += (cx - node.x) * self.gravity
                    node.vy += (cy - node.y) * self.gravity

            # Apply velocity + damping
            for node in node_list:
                if not node.pinned:
                    node.vx *= self.damping
                    node.vy *= self.damping
                    node.x += node.vx
                    node.y += node.vy
                    # Clamp to bounds with padding
                    node.x = max(40, min(self.width - 40, node.x))
                    node.y = max(40, min(self.height - 40, node.y))

    def get_positions(self) -> dict[str, tuple[float, float]]:
        """Return {node_id: (x, y)} for all nodes."""
        return {n.id: (n.x, n.y) for n in self.nodes.values()}
