from __future__ import annotations

from typing import Protocol, TYPE_CHECKING
from remora.core.events.agent_events import _FrozenEvent

if TYPE_CHECKING:
    from cairn import CairnWorkspaceService, AgentWorkspace
    from remora.companion.state import CompanionState

class CompanionHandler(Protocol):
    """Protocol for companion pipeline handlers.
    
    Each handler:
    1. Subscribes to specific event types
    2. Receives the triggering event + current CompanionState
    3. Returns zero or more new events to emit
    4. Has access to its own persistent Cairn workspace
    """
    
    async def handle(
        self,
        event: _FrozenEvent,
        state: CompanionState,
    ) -> list[_FrozenEvent]: ...


class CompanionHandlerBase:
    """Base implementation providing Cairn workspace access."""
    
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._workspace: AgentWorkspace | None = None
    
    async def initialize(self, cairn_service: CairnWorkspaceService) -> None:
        self._workspace = await cairn_service.get_agent_workspace(self.agent_id)
    
    @property
    def workspace(self) -> AgentWorkspace:
        assert self._workspace is not None, "Handler not initialized"
        return self._workspace
