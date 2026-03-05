from __future__ import annotations

import time
from pathlib import Path
from remora.core.events import _FrozenEvent
from remora.companion.events import CompanionContextExtracted, CompanionTaskInferred
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState

class TaskInferrerHandler(CompanionHandlerBase):
    """Infers current task from navigation and context patterns."""
    
    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id)
        self.nav_history: list[str] = []
        self.history_size: int = 20
        self.test_patterns = ["test_", "_test.py", "tests/", "spec_", "_spec."]

    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, CompanionContextExtracted):
            return []
            
        self.nav_history.append(event.file)
        if len(self.nav_history) > self.history_size:
            self.nav_history.pop(0)
            
        recent_unique = len(set(self.nav_history))
        if recent_unique >= 4:
            return [CompanionTaskInferred(
                task_description="Exploring codebase",
                confidence=min(0.9, 0.3 + (recent_unique - 4) * 0.15),
                evidence=(f"Visited {recent_unique} different files",)
            )]
            
        toggle_count = 0
        for i in range(1, len(self.nav_history)):
            curr = self.nav_history[i]
            prev = self.nav_history[i - 1]
            if curr == prev: continue
            curr_is_test = any(p in curr for p in self.test_patterns)
            prev_is_test = any(p in prev for p in self.test_patterns)
            if curr_is_test != prev_is_test:
                toggle_count += 1
                
        if toggle_count >= 3:
            return [CompanionTaskInferred(
                task_description="Debugging / running tests",
                confidence=min(0.9, 0.4 + (toggle_count - 3) * 0.15),
                evidence=(f"Toggled betwen test and impl {toggle_count} times",)
            )]
            
        if event.content_type == "markdown":
            return [CompanionTaskInferred(
                task_description="Writing documentation",
                confidence=0.6,
                evidence=(f"Working in docs: {Path(event.file).name}",)
            )]
            
        recent_count = sum(1 for f in self.nav_history[-5:] if f == event.file)
        if recent_count >= 4:
            return [CompanionTaskInferred(
                task_description="Focused coding",
                confidence=0.7,
                evidence=(f"Focused on {event.file}",)
            )]
            
        return []
