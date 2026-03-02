"""Tests for server-side ForceLayout."""

from __future__ import annotations

import math

from remora_demo.web.graph.layout import ForceLayout, LayoutEdge, LayoutNode


class TestLayoutNode:
    def test_defaults(self) -> None:
        n = LayoutNode(id="foo")
        assert n.x == 0.0
        assert n.y == 0.0
        assert n.vx == 0.0
        assert n.vy == 0.0
        assert n.node_type == "function"
        assert n.pinned is False


class TestLayoutEdge:
    def test_defaults(self) -> None:
        e = LayoutEdge(source="a", target="b")
        assert e.edge_type == "calls"


class TestForceLayoutSetGraph:
    def test_empty_graph(self) -> None:
        layout = ForceLayout()
        layout.set_graph([], [])
        assert layout.nodes == {}
        assert layout.edges == []

    def test_adds_nodes(self) -> None:
        layout = ForceLayout()
        layout.set_graph(
            [{"id": "a", "node_type": "file"}, {"id": "b", "node_type": "function"}],
            [],
        )
        assert "a" in layout.nodes
        assert "b" in layout.nodes
        assert layout.nodes["a"].node_type == "file"
        assert layout.nodes["b"].node_type == "function"

    def test_remora_id_preferred_over_id(self) -> None:
        layout = ForceLayout()
        layout.set_graph([{"remora_id": "r1", "id": "fallback"}], [])
        assert "r1" in layout.nodes
        assert "fallback" not in layout.nodes

    def test_preserves_positions_for_existing_nodes(self) -> None:
        layout = ForceLayout()
        layout.set_graph([{"id": "a"}], [])
        layout.nodes["a"].x = 123.0
        layout.nodes["a"].y = 456.0
        # Re-set graph with same node
        layout.set_graph([{"id": "a"}, {"id": "b"}], [])
        assert layout.nodes["a"].x == 123.0
        assert layout.nodes["a"].y == 456.0
        assert "b" in layout.nodes

    def test_adds_edges(self) -> None:
        layout = ForceLayout()
        layout.set_graph(
            [{"id": "a"}, {"id": "b"}],
            [{"from_id": "a", "to_id": "b", "edge_type": "parent_of"}],
        )
        assert len(layout.edges) == 1
        assert layout.edges[0].source == "a"
        assert layout.edges[0].target == "b"
        assert layout.edges[0].edge_type == "parent_of"

    def test_file_nodes_seeded_at_top(self) -> None:
        layout = ForceLayout(height=600)
        layout.set_graph([{"id": "f", "node_type": "file"}], [])
        # File nodes should be seeded near y=100
        assert layout.nodes["f"].y == 100


class TestForceLayoutStep:
    def test_step_zero_nodes_no_error(self) -> None:
        layout = ForceLayout()
        layout.step(10)  # Should not raise

    def test_repulsion_pushes_nodes_apart(self) -> None:
        layout = ForceLayout()
        layout.set_graph([{"id": "a"}, {"id": "b"}], [])
        # Place them very close together
        layout.nodes["a"].x = 100.0
        layout.nodes["a"].y = 100.0
        layout.nodes["a"].vx = 0.0
        layout.nodes["a"].vy = 0.0
        layout.nodes["b"].x = 101.0
        layout.nodes["b"].y = 100.0
        layout.nodes["b"].vx = 0.0
        layout.nodes["b"].vy = 0.0

        layout.step(1)
        # After repulsion, a should have moved left, b should have moved right
        assert layout.nodes["a"].x < 100.0
        assert layout.nodes["b"].x > 101.0

    def test_attraction_pulls_linked_nodes(self) -> None:
        layout = ForceLayout(repulsion=0.0, gravity=0.0)  # Disable other forces
        layout.set_graph(
            [{"id": "a"}, {"id": "b"}],
            [{"from_id": "a", "to_id": "b"}],
        )
        # Place them far apart
        layout.nodes["a"].x = 100.0
        layout.nodes["a"].y = 300.0
        layout.nodes["a"].vx = 0.0
        layout.nodes["a"].vy = 0.0
        layout.nodes["b"].x = 700.0
        layout.nodes["b"].y = 300.0
        layout.nodes["b"].vx = 0.0
        layout.nodes["b"].vy = 0.0

        layout.step(1)
        # a should have moved right (toward b), b should have moved left (toward a)
        assert layout.nodes["a"].x > 100.0
        assert layout.nodes["b"].x < 700.0

    def test_gravity_pulls_toward_center(self) -> None:
        layout = ForceLayout(width=900, height=600, repulsion=0.0, attraction=0.0)
        layout.set_graph([{"id": "a"}], [])
        # Place node far from center
        layout.nodes["a"].x = 40.0
        layout.nodes["a"].y = 40.0
        layout.nodes["a"].vx = 0.0
        layout.nodes["a"].vy = 0.0

        layout.step(1)
        # Should move toward center (450, 300)
        assert layout.nodes["a"].x > 40.0
        assert layout.nodes["a"].y > 40.0

    def test_pinned_nodes_do_not_move(self) -> None:
        layout = ForceLayout()
        layout.set_graph([{"id": "a"}, {"id": "b"}], [])
        layout.nodes["a"].x = 100.0
        layout.nodes["a"].y = 100.0
        layout.nodes["a"].pinned = True
        layout.nodes["b"].x = 101.0
        layout.nodes["b"].y = 100.0

        layout.step(10)
        assert layout.nodes["a"].x == 100.0
        assert layout.nodes["a"].y == 100.0

    def test_positions_clamped_to_bounds(self) -> None:
        layout = ForceLayout(width=900, height=600)
        layout.set_graph([{"id": "a"}], [])
        layout.nodes["a"].x = 10000.0
        layout.nodes["a"].y = 10000.0
        layout.nodes["a"].vx = 0.0
        layout.nodes["a"].vy = 0.0

        layout.step(1)
        assert layout.nodes["a"].x <= 860.0  # width - 40
        assert layout.nodes["a"].y <= 560.0  # height - 40

    def test_convergence_after_many_steps(self) -> None:
        """After many iterations, velocities should be near zero (stable)."""
        layout = ForceLayout()
        layout.set_graph(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            [{"from_id": "a", "to_id": "b"}, {"from_id": "b", "to_id": "c"}],
        )
        layout.step(200)
        for node in layout.nodes.values():
            assert abs(node.vx) < 1.0, f"{node.id} vx={node.vx} not converged"
            assert abs(node.vy) < 1.0, f"{node.id} vy={node.vy} not converged"


class TestForceLayoutGetPositions:
    def test_returns_dict_of_tuples(self) -> None:
        layout = ForceLayout()
        layout.set_graph([{"id": "a"}, {"id": "b"}], [])
        layout.nodes["a"].x = 10.0
        layout.nodes["a"].y = 20.0
        layout.nodes["b"].x = 30.0
        layout.nodes["b"].y = 40.0

        positions = layout.get_positions()
        assert positions == {"a": (10.0, 20.0), "b": (30.0, 40.0)}

    def test_empty_graph_returns_empty(self) -> None:
        layout = ForceLayout()
        assert layout.get_positions() == {}
