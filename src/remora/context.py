"""Context Builder - Two-Track Memory implementation.

This module provides bounded context for agents by:
- Short Track: Rolling window of recent actions (deque with maxlen)
- Long Track: Full event stream via EventBus subscription

Usage:
    builder = ContextBuilder(window_size=20, store=node_store)

    # Subscribe to events
    event_bus.subscribe(ToolResultEvent, builder.handle)
    event_bus.subscribe(AgentCompleteEvent, builder.handle)

    # Build context for a node
    context = builder.build_context_for(node)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from remora.workspace import ResultSummary

if TYPE_CHECKING:
    from remora.discovery import CSTNode
    from remora.events import AgentCompleteEvent, RemoraEvent, ToolResultEvent


@dataclass
class RecentAction:
    """A recent action for the Short Track."""

    tool: str
    outcome: str
    summary: str
    timestamp: float = field(default_factory=time.time)


def _summarize_output(output: Any, max_length: int = 100) -> str:
    """Truncate and summarize tool output for the Short Track."""
    if output is None:
        return "no output"

    if isinstance(output, dict):
        keys = list(output.keys())[:3]
        return f"dict({', '.join(keys)})"

    if isinstance(output, list):
        return f"list[{len(output)} items]"

    s = str(output)
    if len(s) > max_length:
        return s[: max_length - 3] + "..."
    return s


def _extract_knowledge(result: dict[str, Any]) -> str:
    """Extract key information from agent result for knowledge accumulation."""
    if not result:
        return "no result"

    if "summary" in result:
        return str(result["summary"])

    if "message" in result:
        msg = result["message"]
        if isinstance(msg, dict) and "content" in msg:
            content = msg["content"]
            if len(content) > 100:
                return content[:97] + "..."
            return content

    keys = [k for k in result.keys() if not k.startswith("_")]
    if keys:
        return f"fields: {', '.join(keys[:5])}"

    return "completed"


class ContextBuilder:
    """Builds bounded context from the event stream.

    Implements the Two-Track Memory concept:
    - Short Track: Rolling window of recent actions (via deque with maxlen)
    - Long Track: Full event stream (via EventBus subscription)
    """

    def __init__(
        self,
        window_size: int = 20,
        store: Any = None,
    ):
        """Initialize the ContextBuilder."""
        self._recent: deque[RecentAction] = deque(maxlen=window_size)
        self._knowledge: dict[str, str] = {}
        self._store = store

    async def handle(self, event: RemoraEvent) -> None:
        """EventBus subscriber - updates context from events."""
        event_type = type(event).__name__

        if event_type == "ToolResultEvent":
            tool_label = getattr(event, "tool_name", None) or getattr(event, "name", "unknown")
            summary_input = getattr(event, "output", None) or getattr(event, "output_preview", None)
            self._recent.append(
                RecentAction(
                    tool=tool_label,
                    outcome="error" if getattr(event, "is_error", False) else "success",
                    summary=_summarize_output(summary_input),
                )
            )

        elif event_type == "AgentCompleteEvent":
            aid = getattr(event, "agent_id", None)
            result = getattr(event, "result", None)
            if aid and result:
                self._knowledge[aid] = _extract_knowledge(result)

    def build_prompt_section(self) -> str:
        """Render current Short Track as a prompt section."""
        lines = ["## Recent Actions"]

        recent_list = list(self._recent)
        for action in recent_list[-10:]:
            status = "✓" if action.outcome == "success" else "✗"
            lines.append(f"- {status} {action.tool}: {action.summary}")

        if self._knowledge:
            lines.append("\n## Knowledge")
            for agent_id, knowledge in self._knowledge.items():
                lines.append(f"- {agent_id}: {knowledge}")

        return "\n".join(lines)

    def build_context_for(self, node: Any) -> str:
        """Build full context: Hub index data + Short Track."""
        sections = []

        if self._store:
            try:
                related = self._store.get_related(getattr(node, "node_id", None))
                if related:
                    sections.append("## Related Code")
                    for rel in related[:5]:
                        sections.append(f"- {rel}")
            except Exception:
                pass

        sections.append(self.build_prompt_section())

        return "\n".join(sections)

    def ingest_summary(self, summary: ResultSummary) -> None:
        """Ingest a run summary to enrich the Long Track knowledge."""
        if not summary.agent_id:
            return
        self._knowledge[summary.agent_id] = summary.brief()

    def get_recent_actions(self) -> list[RecentAction]:
        """Get all recent actions (Short Track)."""
        return list(self._recent)

    def get_knowledge(self) -> dict[str, str]:
        """Get accumulated knowledge (Long Track summary)."""
        return self._knowledge.copy()

    def clear(self) -> None:
        """Clear all context. Useful for new sessions."""
        self._recent.clear()
        self._knowledge.clear()


__all__ = [
    "ContextBuilder",
    "RecentAction",
]
