"""Tests for agent state models and state manager.

Tests:
1. AgentTurnState model behavior
2. AgentMemory model behavior
3. AgentExecutionMetrics model behavior
4. RemoraStateManager with mocked Cairn backend
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agents.state_manager import (
    AgentExecutionMetrics,
    AgentMemory,
    AgentTurnState,
)


class TestAgentTurnState:
    """Tests for AgentTurnState model."""

    def test_default_values(self) -> None:
        """AgentTurnState should have sensible defaults."""
        state = AgentTurnState()
        assert state.turn_number == 0
        assert state.last_response is None
        assert state.last_tool_calls == []
        assert state.accumulated_context == {}
        assert state.created_at is not None
        assert state.updated_at is not None

    def test_record_turn_increments_number(self) -> None:
        """record_turn should increment turn_number."""
        state = AgentTurnState(turn_number=5)
        new_state = state.record_turn()
        assert new_state.turn_number == 6
        # Original unchanged (immutable pattern)
        assert state.turn_number == 5

    def test_record_turn_sets_response(self) -> None:
        """record_turn should set last_response."""
        state = AgentTurnState()
        new_state = state.record_turn(response="Hello!")
        assert new_state.last_response == "Hello!"

    def test_record_turn_sets_tool_calls(self) -> None:
        """record_turn should set last_tool_calls."""
        state = AgentTurnState()
        tool_calls = [{"name": "read_file", "args": {"path": "/foo"}}]
        new_state = state.record_turn(tool_calls=tool_calls)
        assert new_state.last_tool_calls == tool_calls

    def test_record_turn_preserves_accumulated_context(self) -> None:
        """record_turn should preserve accumulated_context."""
        state = AgentTurnState(accumulated_context={"key": "value"})
        new_state = state.record_turn(response="test")
        assert new_state.accumulated_context == {"key": "value"}

    def test_record_turn_preserves_created_at(self) -> None:
        """record_turn should preserve original created_at."""
        state = AgentTurnState()
        original_created = state.created_at
        new_state = state.record_turn()
        assert new_state.created_at == original_created

    def test_record_turn_updates_updated_at(self) -> None:
        """record_turn should update updated_at."""
        # Create state with older timestamp
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        state = AgentTurnState(updated_at=old_time)
        new_state = state.record_turn()
        assert new_state.updated_at > old_time

    def test_serialization_roundtrip(self) -> None:
        """AgentTurnState should serialize and deserialize correctly."""
        state = AgentTurnState(
            turn_number=3,
            last_response="test response",
            last_tool_calls=[{"name": "tool1"}],
            accumulated_context={"data": [1, 2, 3]},
        )
        data = state.model_dump(mode="json")
        restored = AgentTurnState.model_validate(data)
        assert restored.turn_number == state.turn_number
        assert restored.last_response == state.last_response
        assert restored.last_tool_calls == state.last_tool_calls
        assert restored.accumulated_context == state.accumulated_context


class TestAgentMemory:
    """Tests for AgentMemory model."""

    def test_default_values(self) -> None:
        """AgentMemory should have empty defaults."""
        memory = AgentMemory()
        assert memory.facts == []
        assert memory.learned_patterns == {}
        assert memory.file_summaries == {}

    def test_add_fact(self) -> None:
        """add_fact should append to facts list."""
        memory = AgentMemory()
        memory.add_fact("User prefers dark mode")
        assert "User prefers dark mode" in memory.facts

    def test_add_fact_no_duplicates(self) -> None:
        """add_fact should not add duplicate facts."""
        memory = AgentMemory()
        memory.add_fact("fact1")
        memory.add_fact("fact1")
        assert memory.facts == ["fact1"]

    def test_add_pattern(self) -> None:
        """add_pattern should add to learned_patterns."""
        memory = AgentMemory()
        memory.add_pattern("error_handling", "Use try/except blocks")
        assert memory.learned_patterns["error_handling"] == "Use try/except blocks"

    def test_add_pattern_overwrites(self) -> None:
        """add_pattern should overwrite existing pattern."""
        memory = AgentMemory(learned_patterns={"key": "old"})
        memory.add_pattern("key", "new")
        assert memory.learned_patterns["key"] == "new"

    def test_add_file_summary(self) -> None:
        """add_file_summary should add to file_summaries."""
        memory = AgentMemory()
        memory.add_file_summary("/src/main.py", "Main entry point")
        assert memory.file_summaries["/src/main.py"] == "Main entry point"

    def test_add_file_summary_overwrites(self) -> None:
        """add_file_summary should overwrite existing summary."""
        memory = AgentMemory(file_summaries={"/foo": "old"})
        memory.add_file_summary("/foo", "new")
        assert memory.file_summaries["/foo"] == "new"

    def test_serialization_roundtrip(self) -> None:
        """AgentMemory should serialize and deserialize correctly."""
        memory = AgentMemory(
            facts=["fact1", "fact2"],
            learned_patterns={"p1": "value1"},
            file_summaries={"/a": "summary a"},
        )
        data = memory.model_dump(mode="json")
        restored = AgentMemory.model_validate(data)
        assert restored.facts == memory.facts
        assert restored.learned_patterns == memory.learned_patterns
        assert restored.file_summaries == memory.file_summaries


class TestAgentExecutionMetrics:
    """Tests for AgentExecutionMetrics model."""

    def test_default_values(self) -> None:
        """AgentExecutionMetrics should have zero defaults."""
        metrics = AgentExecutionMetrics()
        assert metrics.total_turns == 0
        assert metrics.total_tokens_used == 0
        assert metrics.total_tool_calls == 0
        assert metrics.successful_tool_calls == 0
        assert metrics.failed_tool_calls == 0
        assert metrics.files_read == 0
        assert metrics.files_written == 0
        assert metrics.start_time is None
        assert metrics.end_time is None

    def test_record_tool_call_success(self) -> None:
        """record_tool_call should increment success counts."""
        metrics = AgentExecutionMetrics()
        metrics.record_tool_call(success=True)
        assert metrics.total_tool_calls == 1
        assert metrics.successful_tool_calls == 1
        assert metrics.failed_tool_calls == 0

    def test_record_tool_call_failure(self) -> None:
        """record_tool_call should increment failure counts."""
        metrics = AgentExecutionMetrics()
        metrics.record_tool_call(success=False)
        assert metrics.total_tool_calls == 1
        assert metrics.successful_tool_calls == 0
        assert metrics.failed_tool_calls == 1

    def test_record_tool_call_multiple(self) -> None:
        """record_tool_call should accumulate correctly."""
        metrics = AgentExecutionMetrics()
        metrics.record_tool_call(success=True)
        metrics.record_tool_call(success=True)
        metrics.record_tool_call(success=False)
        assert metrics.total_tool_calls == 3
        assert metrics.successful_tool_calls == 2
        assert metrics.failed_tool_calls == 1

    def test_duration_seconds_none_when_incomplete(self) -> None:
        """duration_seconds should be None when times not set."""
        metrics = AgentExecutionMetrics()
        assert metrics.duration_seconds is None

        metrics.start_time = datetime.now(timezone.utc)
        assert metrics.duration_seconds is None

    def test_duration_seconds_calculated(self) -> None:
        """duration_seconds should calculate difference."""
        start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
        metrics = AgentExecutionMetrics(start_time=start, end_time=end)
        assert metrics.duration_seconds == 30.0

    def test_serialization_roundtrip(self) -> None:
        """AgentExecutionMetrics should serialize and deserialize correctly."""
        metrics = AgentExecutionMetrics(
            total_turns=5,
            total_tokens_used=1000,
            total_tool_calls=10,
            successful_tool_calls=8,
            failed_tool_calls=2,
            files_read=15,
            files_written=3,
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        data = metrics.model_dump(mode="json")
        restored = AgentExecutionMetrics.model_validate(data)
        assert restored.total_turns == metrics.total_turns
        assert restored.total_tokens_used == metrics.total_tokens_used
        assert restored.duration_seconds == metrics.duration_seconds


class TestRemoraStateManager:
    """Tests for RemoraStateManager with mocked Cairn backend."""

    @pytest.fixture
    def mock_cairn_state(self) -> MagicMock:
        """Create a mock Cairn AgentStateManager."""
        mock = MagicMock()
        mock.get = AsyncMock(return_value=None)
        mock.set = AsyncMock()
        mock.delete = AsyncMock(return_value=True)
        mock.get_typed = AsyncMock(return_value=None)
        mock.set_typed = AsyncMock()
        mock.increment_turn = AsyncMock(return_value=1)
        mock.get_turn = AsyncMock(return_value=0)
        mock.clear_all = AsyncMock(return_value=0)
        return mock

    @pytest.fixture
    def mock_workspace(self) -> MagicMock:
        """Create a mock AgentWorkspace."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_get_turn_state_returns_default(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """get_turn_state should return default when not persisted."""
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            state = await manager.get_turn_state()
            assert isinstance(state, AgentTurnState)
            assert state.turn_number == 0

    @pytest.mark.asyncio
    async def test_get_turn_state_returns_persisted(
        self, mock_workspace: MagicMock, mock_cairn_state: MagicMock
    ) -> None:
        """get_turn_state should return persisted state."""
        mock_cairn_state.get_typed = AsyncMock(return_value=AgentTurnState(turn_number=5))
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            state = await manager.get_turn_state()
            assert state.turn_number == 5

    @pytest.mark.asyncio
    async def test_save_turn_state_calls_cairn(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """save_turn_state should call Cairn set_typed."""
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            state = AgentTurnState(turn_number=3)
            await manager.save_turn_state(state)
            mock_cairn_state.set_typed.assert_called_once_with("turn_state", state)

    @pytest.mark.asyncio
    async def test_record_turn_loads_saves_increments(
        self, mock_workspace: MagicMock, mock_cairn_state: MagicMock
    ) -> None:
        """record_turn should load, increment, and save state."""
        mock_cairn_state.get_typed = AsyncMock(return_value=AgentTurnState(turn_number=2))
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            new_state = await manager.record_turn(response="Hello")

            assert new_state.turn_number == 3
            assert new_state.last_response == "Hello"
            mock_cairn_state.set_typed.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_memory_returns_default(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """get_memory should return empty memory when not persisted."""
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            memory = await manager.get_memory()
            assert isinstance(memory, AgentMemory)
            assert memory.facts == []

    @pytest.mark.asyncio
    async def test_save_memory_calls_cairn(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """save_memory should call Cairn set_typed."""
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            memory = AgentMemory(facts=["fact1"])
            await manager.save_memory(memory)
            mock_cairn_state.set_typed.assert_called_once_with("memory", memory)

    @pytest.mark.asyncio
    async def test_get_metrics_returns_default(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """get_metrics should return empty metrics when not persisted."""
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            metrics = await manager.get_metrics()
            assert isinstance(metrics, AgentExecutionMetrics)
            assert metrics.total_turns == 0

    @pytest.mark.asyncio
    async def test_increment_turn_delegates_to_cairn(
        self, mock_workspace: MagicMock, mock_cairn_state: MagicMock
    ) -> None:
        """increment_turn should delegate to Cairn."""
        mock_cairn_state.increment_turn = AsyncMock(return_value=5)
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            turn = await manager.increment_turn()
            assert turn == 5
            mock_cairn_state.increment_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_turn_delegates_to_cairn(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """get_turn should delegate to Cairn."""
        mock_cairn_state.get_turn = AsyncMock(return_value=7)
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            turn = await manager.get_turn()
            assert turn == 7

    @pytest.mark.asyncio
    async def test_generic_get_set(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """get/set should delegate to Cairn for arbitrary keys."""
        mock_cairn_state.get = AsyncMock(return_value="test_value")
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            await manager.set("custom_key", "custom_value")
            mock_cairn_state.set.assert_called_with("custom_key", "custom_value")

            value = await manager.get("custom_key")
            assert value == "test_value"

    @pytest.mark.asyncio
    async def test_agent_id_property(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """agent_id property should return the agent ID."""
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "my-agent")
            assert manager.agent_id == "my-agent"

    @pytest.mark.asyncio
    async def test_clear_all_delegates_to_cairn(self, mock_workspace: MagicMock, mock_cairn_state: MagicMock) -> None:
        """clear_all should delegate to Cairn."""
        mock_cairn_state.clear_all = AsyncMock(return_value=5)
        with patch(
            "remora.core.state_manager.CairnStateManager",
            return_value=mock_cairn_state,
        ):
            from remora.core.agents.state_manager import RemoraStateManager

            manager = RemoraStateManager(mock_workspace, "agent-1")
            count = await manager.clear_all()
            assert count == 5
            mock_cairn_state.clear_all.assert_called_once()
