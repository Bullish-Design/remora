"""Context builder for Two-Track Memory.

Short Track: Rolling deque of recent actions
Long Track: Full event subscription for knowledge accumulation

The ContextBuilder subscribes to the EventBus and builds bounded
context for agent prompts.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from remora.core.events import (
    RemoraEvent,
    ToolResultEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
)
from remora.utils import summarize

if TYPE_CHECKING:
    from remora.core.discovery import CSTNode

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecentAction:
    """A recent tool/agent action for Short Track memory."""

    tool: str
    outcome: str  # "success", "error", "partial"
    summary: str
    agent_id: str | None = None


@dataclass
class ContextBuilder:
    """Builds bounded context from the event stream.

    Implements Two-Track Memory:
    - Short Track: Rolling window of recent actions (bounded deque)
    - Long Track: Knowledge accumulated from completed agents
    """

    window_size: int = 20
    _recent: deque[RecentAction] = field(default_factory=deque)
    _knowledge: dict[str, str] = field(default_factory=dict)
    _store: Any = None

    def __post_init__(self):
        self._recent = deque(maxlen=self.window_size)

    async def handle(self, event: RemoraEvent) -> None:
        """EventBus subscriber - updates context from events.

        Async to match EventBus handler expectations and allow future async work.
        """
        match event:
            case ToolResultEvent(tool_name=name, output_preview=output, is_error=is_error):
                self._recent.append(
                    RecentAction(
                        tool=name,
                        outcome="error" if is_error else "success",
                        summary=summarize(str(output), max_len=200),
                    )
                )

            case AgentCompleteEvent(agent_id=aid, result_summary=summary):
                self._knowledge[aid] = summary

            case AgentErrorEvent(agent_id=aid, error=error):
                self._recent.append(
                    RecentAction(
                        tool="agent",
                        outcome="error",
                        summary=f"Agent {aid} failed: {error[:100]}",
                        agent_id=aid,
                    )
                )

            case _:
                pass

    def build_context_for(self, node: CSTNode) -> str:
        """Build full context for an agent prompt."""
        sections: list[str] = []

        if self._store:
            try:
                related = self._store.get_related(getattr(node, "node_id", None))
                if related:
                    sections.append("## Related Code")
                    for rel in related[:5]:
                        sections.append(f"- {rel}")
            except Exception as e:
                logger.warning("Failed to load related code for %s: %s", node.node_id, e)

        if self._recent:
            sections.append("\n## Recent Actions")
            for action in self._recent:
                status = "+" if action.outcome == "success" else "-"
                sections.append(f"[{status}] {action.tool}: {action.summary}")

        if self._knowledge:
            sections.append("\n## Prior Analysis")
            for agent_id, knowledge in list(self._knowledge.items())[-5:]:
                sections.append(f"- {agent_id}: {knowledge[:200]}")

        return "\n".join(sections)

    def build_prompt_section(self) -> str:
        """Render just the recent actions as a prompt section."""
        if not self._recent:
            return ""

        lines = ["## Recent Activity"]
        for action in self._recent:
            status = "+" if action.outcome == "success" else "-"
            lines.append(f"[{status}] {action.tool}: {action.summary}")

        return "\n".join(lines)

    def get_recent_actions(self) -> list[RecentAction]:
        """Return a snapshot of recent actions for testing or inspection."""
        return list(self._recent)

    def get_knowledge(self) -> dict[str, str]:
        """Return a snapshot of accumulated knowledge."""
        return dict(self._knowledge)

    def ingest_summary(self, summary: Any) -> None:
        """Ingest an external summary record into the long track."""
        agent_id = getattr(summary, "agent_id", None)
        if not agent_id:
            return

        success = getattr(summary, "success", None)
        output = getattr(summary, "output", "")
        error = getattr(summary, "error", None)

        if success is True:
            text = f"success: {str(output)[:200]}"
        elif success is False:
            text = f"error: {str(error)[:200]}" if error else "error: unknown"
        else:
            text = str(output)[:200]

        self._knowledge[str(agent_id)] = text

    def clear(self) -> None:
        """Clear all context. Used for testing or new graph runs."""
        self._recent.clear()
        self._knowledge.clear()


__all__ = [
    "ContextBuilder",
    "RecentAction",
]
