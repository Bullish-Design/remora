"""Tests for Two-Track Memory models."""

from remora.context.models import DecisionPacket


class TestDecisionPacket:
    def test_create_minimal(self):
        """Can create a packet with required fields only."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Fix lint errors",
            operation="lint",
            node_id="foo.py:bar",
        )
        assert packet.turn == 0
        assert packet.recent_actions == []
        assert packet.knowledge == {}

    def test_add_action_maintains_rolling_window(self):
        """Actions beyond max are dropped (oldest first)."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Test",
            operation="lint",
            node_id="test",
        )

        for i in range(15):
            packet.add_action(
                tool=f"tool_{i}",
                summary=f"Action {i}",
                outcome="success",
                max_actions=10,
            )

        assert len(packet.recent_actions) == 10
        assert packet.recent_actions[0].tool == "tool_5"
        assert packet.recent_actions[-1].tool == "tool_14"

    def test_update_knowledge_overwrites(self):
        """Updating knowledge with same key replaces value."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Test",
            operation="lint",
            node_id="test",
        )

        packet.update_knowledge("errors", 5)
        packet.turn = 1
        packet.update_knowledge("errors", 3)

        assert packet.knowledge["errors"].value == 3
        assert packet.knowledge["errors"].source_turn == 1

    def test_error_tracking(self):
        """Error count accumulates, last_error can be cleared."""
        packet = DecisionPacket(
            agent_id="test-001",
            goal="Test",
            operation="lint",
            node_id="test",
        )

        packet.record_error("First error")
        packet.record_error("Second error")

        assert packet.error_count == 2
        assert packet.last_error == "Second error"

        packet.clear_error()
        assert packet.last_error is None
        assert packet.error_count == 2
