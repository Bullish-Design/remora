"""Session summarizer composer agent.

Subscribes to SessionTick events and composes a running session summary.
Reads workspace state to gather files touched, insights, questions, and
open threads. Writes to /companion/output/session_summary.md.

No LLM needed — uses heuristic composition from workspace state.
"""

import time
from dataclasses import dataclass
from typing import Any

from remora_demo.companion.agents.base import (
    AgentActivation,
    AgentBase,
    WorkspaceInterface,
    subscribe,
)
from remora_demo.companion.models.events import SessionTick
from remora_demo.companion.models.workspace import (
    Connection,
    EditSummary,
    Question,
    TaskInference,
)


@dataclass
class SessionSummarizerConfig:
    """Configuration for session summarizer."""

    max_files_shown: int = 10  # Maximum number of files to list
    max_connections_shown: int = 5
    max_questions_shown: int = 5


class SessionSummarizer(AgentBase):
    """Composes a running session summary from workspace state.

    Subscribes to: SessionTick events
    Writes to: /companion/output/session_summary.md
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: SessionSummarizerConfig | None = None,
    ) -> None:
        super().__init__("session_summarizer")
        self.workspace = workspace
        self.config = config or SessionSummarizerConfig()

    @subscribe(SessionTick)
    async def on_session_tick(self, event: SessionTick) -> None:
        """Handle a session tick and update the summary."""
        activation = AgentActivation(
            id=f"session_summarizer_{event.tick_number}",
            agent_name=self.name,
            trigger=f"SessionTick:{event.tick_number}",
            started_at=time.time(),
        )
        self.record_input("SessionTick", {"elapsed_ms": event.elapsed_ms, "tick_number": event.tick_number})

        markdown = await self._compose(event)

        await self.workspace.write("/companion/output/session_summary.md", markdown)
        self.record_output("/companion/output/session_summary.md")

        activation.ended_at = time.time()
        activation.status = "success"
        self._activations.append(activation)

    async def _compose(self, event: SessionTick) -> str:
        """Compose the session summary markdown."""
        lines: list[str] = []

        # Header
        elapsed = _format_elapsed(event.elapsed_ms)
        lines.append("# Session Summary\n")
        lines.append(f"> Elapsed: {elapsed}")
        lines.append(f"> Tick: {event.tick_number}\n")
        lines.append("---\n")

        # Files touched
        edit_paths = await self.workspace.list("/companion/session/edits/*")
        files_seen: list[str] = []
        for path in edit_paths:
            edit: EditSummary | None = await self.workspace.read(path)
            if edit and edit.file not in files_seen:
                files_seen.append(edit.file)

        if files_seen:
            lines.append("## Files Touched\n")
            shown = files_seen[: self.config.max_files_shown]
            for f in shown:
                lines.append(f"- `{f}`")
            remaining = len(files_seen) - len(shown)
            if remaining > 0:
                lines.append(f"- ...and {remaining} more")
            lines.append("")

        # Current task / key insights
        inferred_task: TaskInference | None = await self.workspace.read("/companion/analysis/inferred_task")
        connection_paths = await self.workspace.list("/companion/analysis/connections/*")
        connections: list[Connection] = []
        for path in connection_paths[: self.config.max_connections_shown]:
            conn = await self.workspace.read(path)
            if conn:
                connections.append(conn)

        if inferred_task or connections:
            lines.append("## Key Insights\n")
            if inferred_task:
                lines.append(f"**Current task:** {inferred_task.description}")
                lines.append(f"Confidence: {int(inferred_task.confidence * 100)}%\n")
            if connections:
                lines.append("**Connections discovered:**\n")
                for conn in connections:
                    lines.append(f"- {conn.insight} (`{conn.from_file}` -> `{conn.to_file}`)")
                lines.append("")

        # Open threads / questions
        question_paths = await self.workspace.list("/companion/analysis/questions/*")
        questions: list[Question] = []
        for path in question_paths[: self.config.max_questions_shown]:
            q = await self.workspace.read(path)
            if q:
                questions.append(q)

        if questions:
            lines.append("## Open Threads\n")
            for q in questions:
                lines.append(f"- {q.question}")
            lines.append("")

        # Suggested resume point
        if files_seen:
            lines.append("## Resume Point\n")
            last_file = files_seen[-1]
            lines.append(f"Last edited: `{last_file}`")
            if inferred_task:
                lines.append(f"Was working on: {inferred_task.description}")
            lines.append("")

        # Footer
        lines.append("---\n")
        lines.append(f"<small>Session duration: {elapsed}</small>")

        return "\n".join(lines)

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, SessionTick):
            await self.on_session_tick(data)


def _format_elapsed(ms: int) -> str:
    """Format milliseconds as a human-readable duration."""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    hours = minutes // 60
    minutes = minutes % 60

    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"
