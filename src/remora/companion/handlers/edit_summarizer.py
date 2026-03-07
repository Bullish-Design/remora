from __future__ import annotations

import time
from pathlib import Path
from remora.core.events.agent_events import _FrozenEvent
from remora.core.events.interaction_events import ContentChangedEvent
from remora.companion.events import CompanionEditSummary
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState

def _generate_summary(event: ContentChangedEvent) -> str:
    """Generate a heuristic summary of the edit."""
    file_name = Path(event.path).name
    # ContentChangedEvent only carries a diff payload, so line ranges require diff parsing.
    # But for a heuristic summary, the diff first few lines added/removed will do.
    diff = event.diff or ""
    
    # Try to find the first changed line in unified diff to guess the block
    first_addition = ""
    for line in diff.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            first_addition = line[1:].strip()
            if first_addition:
                break
                
    if not first_addition:
        for line in diff.split("\n"):
            if line.startswith("-") and not line.startswith("---"):
                first_addition = line[1:].strip()
                if first_addition:
                    return f"Deleted content in {file_name}: '{first_addition[:30]}...'"
    
    if not first_addition:
         return f"Edited {file_name}"
         
    if first_addition.startswith(("def ", "async def ")):
        func_name = first_addition.split("(")[0].replace("def ", "").replace("async ", "").strip()
        return f"Edited function '{func_name}' in {file_name}"

    if first_addition.startswith("class "):
        class_name = first_addition.split("(")[0].split(":")[0].replace("class ", "").strip()
        return f"Edited class '{class_name}' in {file_name}"

    if first_addition.startswith(("import ", "from ")):
        return f"Modified imports in {file_name}"

    if file_name.endswith((".md", ".markdown")) and first_addition.startswith("#"):
        heading = first_addition.lstrip("#").strip()
        return f"Edited section '{heading}' in {file_name}"

    return f"Edited {file_name} (near '{first_addition[:30]}...')"


class EditSummarizerHandler(CompanionHandlerBase):
    """Summarizes content edits for task inference and session tracking."""
    
    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id)
        self._edit_count = 0

    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, ContentChangedEvent):
            return []
            
        summary_text = _generate_summary(event)
        
        diff = event.diff or ""
        lines_changed = len([line for line in diff.split("\n") if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))])
        
        # Could use self.workspace to keep a rolling list of edits, as per plan
        summary_event = CompanionEditSummary(
            file=event.path,
            summary=summary_text,
            edit_count=1,
            lines_changed=lines_changed
        )
        self._edit_count += 1
        
        return [summary_event]
