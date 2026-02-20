"""ContextManager - Projects events onto the Decision Packet.

This is the core of the Short Track system. It takes events from
the Long Track and updates the Decision Packet state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from remora.context.models import DecisionPacket

if TYPE_CHECKING:
    from remora.context.summarizers import Summarizer


class ContextManager:
    """Manages the Decision Packet for an agent run.

    The ContextManager is responsible for:
    1. Initializing the packet from initial context
    2. Applying events to update packet state
    3. Providing formatted context for prompts
    4. Integrating external context (Hub Pull Hook)

    Usage:
        ctx = ContextManager(initial_context)
        ctx.apply_event({"type": "tool_result", ...})
        prompt_context = ctx.get_prompt_context()
    """

    MAX_RECENT_ACTIONS = 10

    def __init__(
        self,
        initial_context: dict[str, Any],
        summarizers: dict[str, "Summarizer"] | None = None,
    ) -> None:
        """Initialize the ContextManager.

        Args:
            initial_context: Must contain:
                - agent_id: str
                - goal: str
                - operation: str
                - node_id: str
                - node_summary: str (optional)
            summarizers: Optional dict mapping tool names to Summarizer instances.
        """
        self.packet = DecisionPacket(
            agent_id=initial_context["agent_id"],
            turn=0,
            goal=initial_context["goal"],
            operation=initial_context["operation"],
            node_id=initial_context["node_id"],
            node_summary=initial_context.get("node_summary", ""),
        )
        self._summarizers: dict[str, Summarizer] = summarizers or {}
        self._hub_client: Any = None

    def set_hub_client(self, client: Any) -> None:
        """Set the HubClient for Pull Hook integration (Phase 2)."""
        self._hub_client = client

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply an event to update the Decision Packet.

        This is the main event projection method. It routes events
        to the appropriate handler based on event type.

        Args:
            event: Event dict with at least a "type" field.
        """
        event_type = event.get("type") or event.get("event")

        if event_type == "tool_result":
            self._apply_tool_result(event)
        elif event_type == "turn_start":
            self._apply_turn_start(event)
        elif event_type == "hub_update":
            self._apply_hub_context(event)

    def increment_turn(self) -> None:
        """Increment the turn counter."""
        self.packet.turn += 1

    async def pull_hub_context(self) -> None:
        """Pull fresh context from Hub (Phase 2 integration).

        This is the Pull Hook - called at the start of each turn
        to inject external context into the Decision Packet.
        """
        if self._hub_client is None:
            from remora.context.hub_client import get_hub_client

            self._hub_client = get_hub_client()

        try:
            context = await self._hub_client.get_context([self.packet.node_id])
            if context:
                node_state = context.get(self.packet.node_id)
                if node_state:
                    self.packet.hub_context = {
                        "signature": node_state.signature,
                        "docstring": node_state.docstring,
                        "decorators": node_state.decorators,
                        "related_tests": node_state.related_tests,
                        "complexity": node_state.complexity,
                        "callers": node_state.callers,
                        "has_type_hints": node_state.has_type_hints,
                    }
                    self.packet.hub_freshness = datetime.fromtimestamp(
                        node_state.updated_at,
                        tz=timezone.utc,
                    )
        except Exception:
            pass

    def get_prompt_context(self) -> dict[str, Any]:
        """Get the current packet state for prompt building."""
        return {
            "goal": self.packet.goal,
            "operation": self.packet.operation,
            "node_id": self.packet.node_id,
            "node_summary": self.packet.node_summary,
            "turn": self.packet.turn,
            "recent_actions": [
                {
                    "tool": action.tool,
                    "summary": action.summary,
                    "outcome": action.outcome,
                }
                for action in self.packet.recent_actions
            ],
            "knowledge": {key: entry.value for key, entry in self.packet.knowledge.items()},
            "last_error": self.packet.last_error,
            "hub_context": self.packet.hub_context,
        }

    def register_summarizer(self, tool_name: str, summarizer: "Summarizer") -> None:
        """Register a summarizer for a specific tool."""
        self._summarizers[tool_name] = summarizer

    def _apply_tool_result(self, event: dict[str, Any]) -> None:
        """Handle tool_result events."""
        tool_name = event.get("tool_name") or event.get("tool", "unknown")
        data = event.get("data", {})

        summary = self._extract_summary(tool_name, data)
        outcome = self._determine_outcome(data)

        self.packet.add_action(
            tool=tool_name,
            summary=summary,
            outcome=outcome,
            max_actions=self.MAX_RECENT_ACTIONS,
        )

        knowledge_delta = data.get("knowledge_delta", {})
        for key, value in knowledge_delta.items():
            self.packet.update_knowledge(key, value)

        if outcome == "error":
            error_msg = data.get("error") or data.get("message") or "Unknown error"
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            self.packet.record_error(str(error_msg)[:200])
        else:
            self.packet.clear_error()

    def _apply_turn_start(self, event: dict[str, Any]) -> None:
        """Handle turn_start events."""
        turn = event.get("turn")
        if isinstance(turn, int):
            self.packet.turn = turn

    def _apply_hub_context(self, event: dict[str, Any]) -> None:
        """Handle hub_update events (external context injection)."""
        context = event.get("context", {})
        self.packet.hub_context = context
        self.packet.hub_freshness = datetime.now(timezone.utc)

    def _extract_summary(self, tool_name: str, data: dict[str, Any]) -> str:
        """Extract or generate a summary from tool result data."""
        if "summary" in data and data["summary"]:
            return str(data["summary"])

        if tool_name in self._summarizers:
            try:
                raw_result = data.get("result") or data.get("raw_output") or data
                return self._summarizers[tool_name].summarize(raw_result)
            except Exception:
                pass

        if "error" in data:
            return f"{tool_name} failed"
        return f"Executed {tool_name}"

    def _determine_outcome(self, data: dict[str, Any]) -> str:
        """Determine the outcome from tool result data."""
        if "outcome" in data:
            outcome = data["outcome"]
            if outcome in ("success", "error", "partial"):
                return outcome

        if "error" in data and data["error"]:
            return "error"

        status = data.get("status", "").lower()
        if status in ("error", "failed", "failure"):
            return "error"
        if status in ("partial", "warning"):
            return "partial"

        return "success"
