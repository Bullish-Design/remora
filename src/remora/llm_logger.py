"""Human-readable LLM conversation logger."""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO, cast

from remora.events import EventName

logger = logging.getLogger(__name__)


class LlmConversationLogger:
    """Writes human-readable LLM conversation transcripts.

    Hooks into the existing EventEmitter system and reformats
    structured events into readable conversation logs.
    """

    def __init__(
        self,
        output: Path | TextIO | None = None,
        *,
        include_full_prompts: bool = False,
        max_content_lines: int = 100,
    ) -> None:
        self._output = output
        self._include_full_prompts = include_full_prompts
        self._max_content_lines = max_content_lines
        self._stream: TextIO | None = None
        # buffer for atomic turn logging: agent_id -> list of event payloads
        self._agent_events: dict[str, list[dict[str, Any]]] = {}

    def open(self) -> None:
        output = self._output
        if isinstance(output, Path):
            # Generate timestamped filename for daily rotation
            date_str = datetime.now().strftime("%Y-%m-%d")

            if output.is_dir():
                log_file = output / f"llm_conversations_{date_str}.log"
            else:
                stem = output.stem
                suffix = output.suffix
                log_file = output.with_name(f"{stem}_{date_str}{suffix}")

            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._stream = log_file.open("a", encoding="utf-8")
        elif hasattr(output, "write"):
            self._stream = output

    def close(self) -> None:
        self.flush_all()
        if self._stream and isinstance(self._output, Path):
            self._stream.close()

    def flush_all(self) -> None:
        """Force write all buffered conversations."""
        for agent_id in list(self._agent_events.keys()):
            self._flush_agent(agent_id)

    def emit(self, payload: dict[str, Any]) -> None:
        """Buffer an event payload for later processing."""
        agent_id = payload.get("agent_id")
        if not agent_id:
            return

        # Initialize buffer for this agent if needed
        if agent_id not in self._agent_events:
            self._agent_events[agent_id] = []

        # Store a shallow copy to prevent mutation of the original event
        # which might be used by other emitters.
        self._agent_events[agent_id].append(payload.copy())

        # Check for completion events to trigger flush
        event_type = payload.get("event")
        if event_type in (EventName.AGENT_COMPLETE, EventName.AGENT_ERROR):
            self._flush_agent(agent_id)

    def _write(self, text: str) -> None:
        if self._stream:
            self._stream.write(text + "\n")
            self._stream.flush()

    def _flush_agent(self, agent_id: str) -> None:
        """Format and write the full conversation for a completed agent."""
        events = self._agent_events.pop(agent_id, [])
        if not events:
            return

        # 1. Identify context from the LAST request (contains full history)
        # We iterate backwards to find the last model_request
        last_request: dict[str, Any] | None = None
        for event in reversed(events):
            if event.get("event") == EventName.MODEL_REQUEST:
                last_request = event
                break

        if last_request is None:
            # Fallback: just print what we have if no request found (unlikely)
            self._write(f"WARNING: No model_request found for {agent_id}")
            # But we continue to print what we have!

        # 2. Print Header
        # If we have a request, use it for metadata. If not, try the first event.
        header_source: dict[str, Any] = last_request if last_request else events[0]
        self._write_agent_header(header_source)

        # 3. Print History (from last request's messages)
        # This includes System, User, and all previous Turns (Model/Tools)
        if last_request:
            messages = last_request.get("messages", [])
            if isinstance(messages, list):
                for msg in messages:
                    if isinstance(msg, dict):
                        self._print_message(msg)

        # 4. Print Subsequent Events (that happened AFTER the last request)
        # This usually includes the final response, tool calls, or errors
        # that weren't part of the history sent in the last request.

        subsequent_events: list[dict[str, Any]] = []
        if last_request:
            # Manually find index to avoid list.index type issues
            idx = -1
            for i, evt in enumerate(events):
                if evt is last_request:
                    idx = i
                    break

            if idx != -1:
                # Use list comprehension for safe slicing
                subsequent_events = [e for k, e in enumerate(events) if k > idx]
        else:
            # If no request found, everything is "subsequent" (partial log)
            self._write(f"\n  (WARNING: No model request history found - partial log)")
            subsequent_events = events

        for event in subsequent_events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("event")
            if event_type == EventName.MODEL_RESPONSE:
                self._print_model_response(event)
            elif event_type == EventName.TOOL_CALL:
                self._print_tool_call(event)
            elif event_type == EventName.TOOL_RESULT:
                self._print_tool_result(event)
            elif event_type == EventName.AGENT_ERROR:
                self._print_agent_error(event)
            elif event_type == EventName.AGENT_COMPLETE:
                self._print_agent_complete(event)
            elif not last_request and event_type == EventName.MODEL_REQUEST:
                self._write("\n  (Found model_request but failed to identify it as last_request)")
            elif getattr(self, f"_print_{event_type}", None):
                # For any other event, see if we have a custom printer.
                getattr(self, f"_print_{event_type}")(event)

        self._write(f"{'═' * 60}\n")

    def _print_message(self, msg: dict[str, Any]) -> None:
        role = str(msg.get("role", "?")).upper()
        # Force conversion to string to satisfy type checker for slicing
        content = cast(str, str(msg.get("content") or ""))

        if role == "SYSTEM":
            self._write(f"\n── System Prompt {'─' * 42}")
            self._write(textwrap.indent(content[:2000], "  "))
        elif role == "USER":
            self._write(f"\n── Turn (user) {'─' * 44}")
            self._write(f"→ {role}:")
            self._write(textwrap.indent(content[:2000], "  "))
        elif role == "ASSISTANT":
            # In history, assistant messages are previous turns
            self._write(f"\n← MODEL (history):")
            if content:
                self._write(textwrap.indent(content[:2000], "  "))

            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        func = tc.get("function", {})
                        if isinstance(func, dict):
                            name = func.get("name", "?")
                            args = func.get("arguments", "{}")
                            self._write(f"  ⚙ TOOL CALL: {name}")
                            self._write(textwrap.indent(f"Args: {args}", "    "))

        elif role == "TOOL":
            name = msg.get("name", "?")
            self._write(f"    → {name} [history]")
            if content:
                self._write(textwrap.indent(content[:1000], "      "))

    def _print_model_response(self, p: dict[str, Any]) -> None:
        status = p.get("status", "?")
        duration = p.get("duration_ms", "?")
        tokens = p.get("total_tokens", "?")
        response = cast(str, str(p.get("response_text") or ""))

        self._write(f"\n← MODEL RESPONSE ({duration}ms, {tokens} tokens) [{status}]:")
        if response:
            self._write(textwrap.indent(response[:2000], "  "))

        if p.get("error"):
            self._write(f"  ERROR: {p['error']}")

    def _print_tool_call(self, p: dict[str, Any]) -> None:
        tool = p.get("tool_name", "?")
        self._write(f"\n  ⚙ TOOL CALL: {tool}")

    def _print_tool_result(self, p: dict[str, Any]) -> None:
        tool = p.get("tool_name", "?")
        status = p.get("status", "?")
        output = cast(str, str(p.get("tool_output") or ""))
        self._write(f"    → {tool} [{status}]")
        if output:
            self._write(textwrap.indent(output[:1000], "      "))

    def _print_agent_error(self, p: dict[str, Any]) -> None:
        self._write(f"\n{'!' * 60}")
        self._write(f"AGENT ERROR: {p.get('error', '?')}")
        self._write(f"  Phase: {p.get('phase')}")
        if p.get("error_code"):
            self._write(f"  Code: {p['error_code']}")
        self._write(f"{'!' * 60}")

    def _print_agent_complete(self, p: dict[str, Any]) -> None:
        self._write("\n── Agent Complete " + "─" * 42)
        turn_count = p.get("turn_count")
        termination_reason = p.get("termination_reason")
        total_duration_ms = p.get("total_duration_ms")
        if turn_count is not None:
            self._write(f"  turns: {turn_count}")
        if termination_reason:
            self._write(f"  termination_reason: {termination_reason}")
        if total_duration_ms is not None:
            self._write(f"  total_duration_ms: {total_duration_ms}")

    def _write_agent_header(self, p: dict[str, Any]) -> None:
        self._write(f"\n{'═' * 60}")
        self._write(f"AGENT: {p.get('agent_id', '?')} | Op: {p.get('operation', '?')}")
        self._write(f"Model: {p.get('model', '?')}")
        self._write(f"Time: {datetime.now(timezone.utc).isoformat()}")
        self._write(f"{'═' * 60}")
