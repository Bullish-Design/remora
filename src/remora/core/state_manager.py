"""Agent state persistence via Cairn KV store.

Wraps Cairn's AgentStateManager with Remora-specific typed models
for turn state, memory, and metrics.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cairn import AgentStateManager as CairnStateManager

from remora.core.agent_state import (
    AgentExecutionMetrics,
    AgentMemory,
    AgentTurnState,
)

if TYPE_CHECKING:
    from remora.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)


class RemoraStateManager:
    """Remora wrapper around Cairn's AgentStateManager.

    Provides typed access to agent state with Remora-specific models
    for turn state, memory, and execution metrics.

    Example:
        ```python
        state_manager = RemoraStateManager(workspace, "agent-123")

        # Turn state
        turn_state = await state_manager.get_turn_state()
        turn_state = turn_state.record_turn(response="Hello")
        await state_manager.save_turn_state(turn_state)

        # Memory
        memory = await state_manager.get_memory()
        memory.add_fact("User prefers dark mode")
        await state_manager.save_memory(memory)

        # Metrics
        metrics = await state_manager.get_metrics()
        metrics.record_tool_call(success=True)
        await state_manager.save_metrics(metrics)
        ```
    """

    # KV keys for typed state
    KEY_TURN_STATE = "turn_state"
    KEY_MEMORY = "memory"
    KEY_METRICS = "metrics"

    def __init__(self, workspace: "AgentWorkspace", agent_id: str):
        """Create a state manager for an agent.

        Args:
            workspace: The AgentWorkspace containing the Cairn workspace
            agent_id: Unique identifier for the agent (used for namespacing)
        """
        self._workspace = workspace
        self._agent_id = agent_id
        self._cairn_state = CairnStateManager(workspace.cairn, agent_id)

    @property
    def agent_id(self) -> str:
        """The agent ID this manager is scoped to."""
        return self._agent_id

    @property
    def cairn_state(self) -> CairnStateManager:
        """Access the underlying Cairn state manager."""
        return self._cairn_state

    # -------------------------------------------------------------------------
    # Turn State
    # -------------------------------------------------------------------------

    async def get_turn_state(self) -> AgentTurnState:
        """Get current turn state.

        Returns:
            AgentTurnState instance (empty state if not yet persisted)
        """
        state = await self._cairn_state.get_typed(self.KEY_TURN_STATE, AgentTurnState)
        return state or AgentTurnState()

    async def save_turn_state(self, state: AgentTurnState) -> None:
        """Save turn state.

        Args:
            state: The turn state to persist
        """
        await self._cairn_state.set_typed(self.KEY_TURN_STATE, state)

    async def record_turn(
        self,
        response: str | None = None,
        tool_calls: list[dict] | None = None,
    ) -> AgentTurnState:
        """Record a new turn and return updated state.

        Convenience method that loads current state, records the turn,
        saves, and returns the new state.

        Args:
            response: Optional response text from this turn
            tool_calls: Optional list of tool calls made this turn

        Returns:
            Updated AgentTurnState
        """
        current = await self.get_turn_state()
        new_state = current.record_turn(response=response, tool_calls=tool_calls)
        await self.save_turn_state(new_state)
        return new_state

    # -------------------------------------------------------------------------
    # Memory
    # -------------------------------------------------------------------------

    async def get_memory(self) -> AgentMemory:
        """Get agent long-term memory.

        Returns:
            AgentMemory instance (empty if not yet persisted)
        """
        memory = await self._cairn_state.get_typed(self.KEY_MEMORY, AgentMemory)
        return memory or AgentMemory()

    async def save_memory(self, memory: AgentMemory) -> None:
        """Save agent memory.

        Args:
            memory: The memory to persist
        """
        await self._cairn_state.set_typed(self.KEY_MEMORY, memory)

    # -------------------------------------------------------------------------
    # Metrics
    # -------------------------------------------------------------------------

    async def get_metrics(self) -> AgentExecutionMetrics:
        """Get execution metrics.

        Returns:
            AgentExecutionMetrics instance (empty if not yet persisted)
        """
        metrics = await self._cairn_state.get_typed(self.KEY_METRICS, AgentExecutionMetrics)
        return metrics or AgentExecutionMetrics()

    async def save_metrics(self, metrics: AgentExecutionMetrics) -> None:
        """Save execution metrics.

        Args:
            metrics: The metrics to persist
        """
        await self._cairn_state.set_typed(self.KEY_METRICS, metrics)

    # -------------------------------------------------------------------------
    # Turn Counter (delegated to Cairn)
    # -------------------------------------------------------------------------

    async def increment_turn(self) -> int:
        """Increment and return turn counter.

        This uses Cairn's built-in turn tracking.

        Returns:
            The new turn number (starts at 1)
        """
        return await self._cairn_state.increment_turn()

    async def get_turn(self) -> int:
        """Get current turn number.

        Returns:
            Current turn number (0 if no turns yet)
        """
        return await self._cairn_state.get_turn()

    # -------------------------------------------------------------------------
    # Generic KV access (delegated to Cairn)
    # -------------------------------------------------------------------------

    async def get(self, key: str, default=None):
        """Get arbitrary state value by key.

        Args:
            key: The state key
            default: Value to return if key doesn't exist

        Returns:
            The stored value, or default if not found
        """
        return await self._cairn_state.get(key, default=default)

    async def set(self, key: str, value) -> None:
        """Set arbitrary state value.

        Args:
            key: The state key
            value: The value to store (must be JSON-serializable)
        """
        await self._cairn_state.set(key, value)

    async def delete(self, key: str) -> bool:
        """Delete state value.

        Args:
            key: The state key to delete

        Returns:
            True if key existed and was deleted
        """
        return await self._cairn_state.delete(key)

    async def clear_all(self) -> int:
        """Clear all state for this agent.

        Returns:
            Number of keys deleted
        """
        return await self._cairn_state.clear_all()


__all__ = ["RemoraStateManager"]
