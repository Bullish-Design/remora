"""Edit summarizer extractor agent.

Subscribes to ContentEdited events and generates brief heuristic summaries
of what changed. Writes EditSummary objects to /companion/session/edits/*.

No LLM needed — uses simple heuristics: file name, line range, and a
brief description based on the edit content.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora_demo.companion.agents.base import (
    AgentActivation,
    AgentBase,
    WorkspaceInterface,
    subscribe,
)
from remora_demo.companion.models.events import ContentEdited
from remora_demo.companion.models.workspace import EditSummary


@dataclass
class EditSummarizerConfig:
    """Configuration for edit summarizer."""

    max_history: int = 100  # Maximum number of edit summaries to keep


class EditSummarizer(AgentBase):
    """Summarizes content edits for task inference and session tracking.

    Subscribes to: ContentEdited events
    Writes to: /companion/session/edits/<index>
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: EditSummarizerConfig | None = None,
    ) -> None:
        super().__init__("edit_summarizer")
        self.workspace = workspace
        self.config = config or EditSummarizerConfig()
        self._edit_count = 0

    @subscribe(ContentEdited)
    async def on_content_edited(self, event: ContentEdited) -> None:
        """Handle a content edited event and write a summary."""
        activation = AgentActivation(
            id=f"edit_summarizer_{self._edit_count}",
            agent_name=self.name,
            trigger=f"ContentEdited:{event.file}",
            started_at=time.time(),
        )
        self.record_input("ContentEdited", {"file": event.file, "lines": f"{event.start_line}-{event.end_line}"})

        summary_text = _generate_summary(event)

        edit_summary = EditSummary(
            file=event.file,
            start_line=event.start_line,
            end_line=event.end_line,
            summary=summary_text,
            timestamp=time.time(),
        )

        path = f"/companion/session/edits/{self._edit_count}"
        await self.workspace.write(path, edit_summary)
        self.record_output(path)

        self._edit_count += 1

        activation.ended_at = time.time()
        activation.status = "success"
        self._activations.append(activation)

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, ContentEdited):
            await self.on_content_edited(data)


def _generate_summary(event: ContentEdited) -> str:
    """Generate a heuristic summary of the edit.

    No LLM — uses file name, line range, and content analysis.
    """
    file_name = Path(event.file).name
    line_count = event.end_line - event.start_line + 1
    text = event.text.strip()

    # Describe the scope
    if line_count == 1:
        scope = f"line {event.start_line}"
    else:
        scope = f"lines {event.start_line}-{event.end_line}"

    # Analyze content to determine edit type
    if not text:
        return f"Deleted content in {file_name} at {scope}"

    lines = text.split("\n")
    first_line = lines[0].strip() if lines else ""

    # Detect common patterns
    if first_line.startswith(("def ", "async def ")):
        func_name = first_line.split("(")[0].replace("def ", "").replace("async ", "").strip()
        return f"Edited function '{func_name}' in {file_name} at {scope}"

    if first_line.startswith("class "):
        class_name = first_line.split("(")[0].split(":")[0].replace("class ", "").strip()
        return f"Edited class '{class_name}' in {file_name} at {scope}"

    if first_line.startswith(("import ", "from ")):
        return f"Modified imports in {file_name} at {scope}"

    if first_line.startswith("#") and file_name.endswith((".md", ".markdown")):
        heading = first_line.lstrip("#").strip()
        return f"Edited section '{heading}' in {file_name} at {scope}"

    if first_line.startswith("#") and not file_name.endswith((".md", ".markdown")):
        return f"Edited comment in {file_name} at {scope}"

    # Generic summary
    if line_count <= 3:
        return f"Small edit in {file_name} at {scope}"
    else:
        return f"Edited {line_count} lines in {file_name} at {scope}"
