"""Event system for Remora.

This module defines:
1. Event names and statuses
2. EventEmitter protocol for output
3. Concrete emitters (JSONL, Null, Composite)

The actual event translation from structured-agents happens in event_bridge.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Protocol, TextIO


class EventName:
    """Standard event names."""

    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"

    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"

    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    TURN_COMPLETE = "turn_complete"

    DISCOVERY = "discovery"

    WORKSPACE_ACCEPTED = "workspace_accepted"
    WORKSPACE_REJECTED = "workspace_rejected"


class EventStatus:
    """Standard status values."""

    OK = "ok"
    ERROR = "error"
    PENDING = "pending"


class EventEmitter(Protocol):
    """Protocol for event output."""

    def emit(self, payload: dict[str, Any]) -> None:
        """Emit an event."""
        ...

    def close(self) -> None:
        """Clean up resources."""
        ...


class NullEventEmitter:
    """Event emitter that discards all events."""

    def emit(self, payload: dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


class JsonlEventEmitter:
    """Event emitter that writes JSONL to a file or stream."""

    def __init__(
        self,
        output: Path | TextIO | None = None,
        include_payloads: bool = True,
        max_payload_chars: int = 40000,
    ):
        self._include_payloads = include_payloads
        self._max_chars = max_payload_chars

        if output is None:
            self._file = sys.stdout
            self._should_close = False
        elif isinstance(output, Path):
            self._file = output.open("a", encoding="utf-8")
            self._should_close = True
        else:
            self._file = output
            self._should_close = False

    def emit(self, payload: dict[str, Any]) -> None:
        """Write event as JSONL."""
        if not self._include_payloads:
            payload = {key: value for key, value in payload.items() if key != "response_preview"}

        try:
            line = json.dumps(payload, default=str)
        except (TypeError, ValueError) as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to serialize event: %s", exc)
            return

        if len(line) > self._max_chars:
            line = line[: self._max_chars] + "..."

        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._should_close:
            self._file.close()


class CompositeEventEmitter:
    """Fan-out to multiple emitters."""

    def __init__(self, emitters: list[EventEmitter]):
        self._emitters = emitters

    def emit(self, payload: dict[str, Any]) -> None:
        for emitter in self._emitters:
            try:
                emitter.emit(payload)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).exception("CompositeEventEmitter failed to emit")

    def close(self) -> None:
        for emitter in self._emitters:
            try:
                emitter.close()
            except Exception:
                pass
