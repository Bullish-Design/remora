"""Bridge between structured-agents observer and Remora's EventEmitter."""

from __future__ import annotations

import time
from typing import Any

from structured_agents import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)

from remora.context import ContextManager
from remora.events import EventEmitter, EventName, EventStatus


class RemoraEventBridge:
    """Translates structured-agents events to Remora's EventEmitter format.

    This bridge:
    1. Receives typed events from structured-agents kernel
    2. Converts them to Remora's event dict format
    3. Emits them via Remora's EventEmitter
    4. Updates Remora's ContextManager with tool results
    """

    def __init__(
        self,
        emitter: EventEmitter,
        context_manager: ContextManager,
        agent_id: str,
        node_id: str,
        operation: str,
    ):
        self._emitter = emitter
        self._context_manager = context_manager
        self._agent_id = agent_id
        self._node_id = node_id
        self._operation = operation
        self._start_time = time.monotonic()

    def _base_payload(self, event_name: str) -> dict[str, Any]:
        """Build base event payload with common fields."""
        return {
            "event": event_name,
            "agent_id": self._agent_id,
            "node_id": self._node_id,
            "operation": self._operation,
            "phase": "execution",
            "timestamp_ms": int(time.time() * 1000),
        }

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        """Handle kernel start event."""
        payload = self._base_payload(EventName.AGENT_START)
        payload["max_turns"] = event.max_turns
        payload["tools_count"] = event.tools_count
        payload["initial_messages_count"] = event.initial_messages_count
        self._emitter.emit(payload)
        self._start_time = time.monotonic()

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        """Handle model request event."""
        payload = self._base_payload(EventName.MODEL_REQUEST)
        payload["turn"] = event.turn
        payload["messages_count"] = event.messages_count
        payload["tools_count"] = event.tools_count
        payload["model"] = event.model
        self._emitter.emit(payload)

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        """Handle model response event."""
        payload = self._base_payload(EventName.MODEL_RESPONSE)
        payload["turn"] = event.turn
        payload["duration_ms"] = event.duration_ms
        payload["tool_calls_count"] = event.tool_calls_count
        payload["status"] = EventStatus.OK

        if event.content:
            payload["response_preview"] = event.content[:500]

        if event.usage:
            payload["usage"] = {
                "prompt_tokens": event.usage.prompt_tokens,
                "completion_tokens": event.usage.completion_tokens,
                "total_tokens": event.usage.total_tokens,
            }

        self._emitter.emit(payload)

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        """Handle tool call event (before execution)."""
        payload = self._base_payload(EventName.TOOL_CALL)
        payload["turn"] = event.turn
        payload["tool_name"] = event.tool_name
        payload["call_id"] = event.call_id
        payload["arguments"] = event.arguments
        self._emitter.emit(payload)

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Handle tool result event."""
        payload = self._base_payload(EventName.TOOL_RESULT)
        payload["turn"] = event.turn
        payload["tool_name"] = event.tool_name
        payload["call_id"] = event.call_id
        payload["duration_ms"] = event.duration_ms
        payload["status"] = EventStatus.ERROR if event.is_error else EventStatus.OK
        payload["output_preview"] = event.output_preview
        self._emitter.emit(payload)

        self._context_manager.apply_event(
            {
                "type": "tool_result",
                "tool_name": event.tool_name,
                "data": {
                    "output_preview": event.output_preview,
                    "is_error": event.is_error,
                },
            }
        )

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        """Handle turn complete event."""
        self._context_manager.apply_event({"type": "turn_start"})

        payload = self._base_payload(EventName.TURN_COMPLETE)
        payload["turn"] = event.turn
        payload["tool_calls_count"] = event.tool_calls_count
        payload["tool_results_count"] = event.tool_results_count
        payload["errors_count"] = event.errors_count
        self._emitter.emit(payload)

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        """Handle kernel end event."""
        payload = self._base_payload(EventName.AGENT_COMPLETE)
        payload["turn_count"] = event.turn_count
        payload["termination_reason"] = event.termination_reason
        payload["total_duration_ms"] = event.total_duration_ms
        self._emitter.emit(payload)

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        """Handle error event."""
        payload = self._base_payload(EventName.AGENT_ERROR)
        payload["error_type"] = type(error).__name__
        payload["error_message"] = str(error)
        payload["context"] = context
        payload["status"] = EventStatus.ERROR
        self._emitter.emit(payload)
