"""FunctionGemma runner implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import time
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam, ChatCompletionToolParam

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode
from remora.events import EventEmitter, NullEventEmitter
from remora.errors import AGENT_002, AGENT_003
from remora.results import AgentResult
from remora.subagent import SubagentDefinition


class CairnClient(Protocol):
    """Protocol for Cairn integration."""

    async def run_pym(self, path: Any, workspace_id: str, inputs: dict[str, Any]) -> dict[str, Any]: ...


class AgentError(RuntimeError):
    def __init__(
        self,
        *,
        node_id: str,
        operation: str,
        phase: Literal["init", "model_load", "loop", "tool", "merge"],
        error_code: str,
        message: str,
        traceback: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.operation = operation
        self.phase = phase
        self.error_code = error_code
        self.message = message
        self.traceback = traceback
        self.timestamp = timestamp or datetime.now(timezone.utc)


@dataclass
class FunctionGemmaRunner:
    definition: SubagentDefinition
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient
    server_config: ServerConfig
    runner_config: RunnerConfig
    adapter_name: str | None = None
    http_client: AsyncOpenAI | None = None
    event_emitter: EventEmitter = field(default_factory=NullEventEmitter)
    messages: list[ChatCompletionMessageParam] = field(init=False)
    turn_count: int = field(init=False)
    _http_client: AsyncOpenAI = field(init=False)
    _system_prompt: str = field(init=False)
    _initial_message: str = field(init=False)
    _model_target: str = field(init=False)

    def __post_init__(self) -> None:
        self._http_client = self.http_client or AsyncOpenAI(
            base_url=self.server_config.base_url,
            api_key=self.server_config.api_key,
            timeout=self.server_config.timeout,
        )
        self._model_target = self.adapter_name or self.server_config.default_adapter
        self.messages = []
        self.turn_count = 0
        self._system_prompt = self._build_system_prompt()
        self._initial_message = self.definition.initial_context.render(self.node)
        self.messages.append(cast(ChatCompletionMessageParam, {"role": "system", "content": self._system_prompt}))
        self.messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": self._initial_message}))

    def _build_system_prompt(self) -> str:
        return self.definition.initial_context.system_prompt

    async def run(self) -> AgentResult:
        message = await self._call_model(phase="model_load", tool_choice=self._tool_choice_for_turn(1))

        while self.turn_count < self.definition.max_turns:
            self.turn_count += 1
            self.messages.append(self._coerce_message_param(message))
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return self._handle_no_tool_calls(message)
            for tool_call in tool_calls:
                tool_function = getattr(tool_call, "function", None)
                name = getattr(tool_function, "name", None)
                if name == "submit_result":
                    return self._build_submit_result(getattr(tool_function, "arguments", None))
                tool_result_content = await self._dispatch_tool(tool_call)
                self.messages.append(
                    cast(
                        ChatCompletionMessageParam,
                        {
                            "role": "tool",
                            "tool_call_id": getattr(tool_call, "id", None) or "unknown",
                            "name": name or "unknown",
                            "content": tool_result_content,
                        },
                    )
                )
            next_turn = self.turn_count + 1
            message = await self._call_model(phase="loop", tool_choice=self._tool_choice_for_turn(next_turn))

        raise AgentError(
            node_id=self.node.node_id,
            operation=self.definition.name,
            phase="loop",
            error_code=AGENT_003,
            message=f"Turn limit {self.definition.max_turns} exceeded",
        )

    async def _call_model(
        self,
        *,
        phase: Literal["model_load", "loop"],
        tool_choice: Any | None = None,
    ) -> ChatCompletionMessage:
        request_id = None
        start = time.monotonic()
        payload: dict[str, Any] = {
            "event": "model_request",
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "phase": phase,
            "model": self._model_target,
        }
        if self._include_payloads():
            payload.update(self._build_message_payload())
        self.event_emitter.emit(payload)
        if tool_choice is None:
            tool_choice = self.runner_config.tool_choice
        tools_payload = self.definition.tool_schemas
        self._emit_tool_debug("model_tools_before", tool_choice)
        self._emit_request_debug(
            model=self._model_target,
            tool_choice=tool_choice,
            tools=tools_payload,
        )
        try:
            response = await self._http_client.chat.completions.create(
                model=self._model_target,
                messages=cast(list[ChatCompletionMessageParam], self.messages),
                tools=cast(list[ChatCompletionToolParam], tools_payload),
                tool_choice=cast(Any, tool_choice),
                max_tokens=self.runner_config.max_tokens,
                temperature=self.runner_config.temperature,
            )
            request_id = getattr(response, "id", None)
        except (APIConnectionError, APITimeoutError) as exc:
            self._emit_model_response(
                start,
                phase=phase,
                request_id=request_id,
                status="error",
                error=str(exc),
            )
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase=phase,
                error_code=AGENT_002,
                message=f"Cannot reach vLLM server at {self.server_config.base_url}",
            ) from exc
        message = response.choices[0].message
        response_text = message.content or ""
        self._emit_tool_debug("model_tools_after", tool_choice, request_id=request_id)
        self._emit_model_response(
            start,
            phase=phase,
            request_id=request_id,
            status="ok",
            usage=getattr(response, "usage", None),
            response_text=response_text,
        )
        return message

    def _coerce_message_param(self, message: ChatCompletionMessage) -> ChatCompletionMessageParam:
        return cast(ChatCompletionMessageParam, message.model_dump(exclude_none=True))

    def _tool_choice_for_turn(self, next_turn: int) -> Any:
        tool_choice: Any = self.runner_config.tool_choice
        if tool_choice == "none":
            return tool_choice
        if next_turn >= self.definition.max_turns:
            return {"type": "function", "function": {"name": "submit_result"}}
        return tool_choice

    def _relative_node_path(self) -> str:
        try:
            return str(self.node.file_path.relative_to(Path.cwd()))
        except ValueError:
            return str(self.node.file_path)

    def _base_tool_inputs(self) -> dict[str, Any]:
        return {
            "node_text": self.node.text,
            "target_file": self._relative_node_path(),
            "workspace_id": self.workspace_id,
        }

    def _handle_no_tool_calls(self, message: ChatCompletionMessage) -> AgentResult:
        if self.runner_config.tool_choice == "required":
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase="loop",
                error_code=AGENT_003,
                message="Model stopped without calling submit_result",
            )
        content = message.content or ""
        if content:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return self._build_submit_result(parsed)
        result_data = {
            "status": "success",
            "workspace_id": self.workspace_id,
            "changed_files": [],
            "summary": content,
            "details": {},
            "error": None,
        }
        return AgentResult.model_validate(result_data)

    def _emit_tool_debug(self, event: str, tool_choice: Any, *, request_id: str | None = None) -> None:
        tools = self.definition.tool_schemas
        payload: dict[str, Any] = {
            "event": event,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "model": self._model_target,
            "tool_count": len(tools),
            "tool_choice": tool_choice,
            "tools_type": type(tools).__name__,
            "tools_item_types": [type(item).__name__ for item in tools],
        }
        if request_id is not None:
            payload["request_id"] = request_id
        if self._include_payloads():
            tools_text = self._serialize_payload(tools)
            payload["tools_chars"] = len(tools_text)
            payload["tools"] = self._truncate(tools_text)
        self.event_emitter.emit(payload)

    def _emit_request_debug(self, *, model: str, tool_choice: Any, tools: list[dict[str, Any]]) -> None:
        payload: dict[str, Any] = {
            "event": "model_request_debug",
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "model": model,
            "tool_choice": tool_choice,
            "tools_count": len(tools),
        }
        if self._include_payloads():
            messages_text = self._serialize_payload(self.messages)
            tools_text = self._serialize_payload(tools)
            request_payload = {
                "model": model,
                "messages": self.messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "max_tokens": self.runner_config.max_tokens,
                "temperature": self.runner_config.temperature,
            }
            request_text = self._serialize_payload(request_payload)
            payload.update(
                {
                    "messages_chars": len(messages_text),
                    "tools_chars": len(tools_text),
                    "messages": messages_text,
                    "tools": tools_text,
                    "request_chars": len(request_text),
                    "request": request_text,
                }
            )
        self.event_emitter.emit(payload)

    def _include_payloads(self) -> bool:
        return bool(getattr(self.event_emitter, "include_payloads", False))

    def _payload_limit(self) -> int:
        limit = getattr(self.event_emitter, "max_payload_chars", 0)
        return int(limit) if limit else 0

    def _truncate(self, text: str) -> str:
        limit = self._payload_limit()
        if limit > 0 and len(text) > limit:
            return f"{text[:limit]}…"
        return text

    def _serialize_payload(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def _build_message_payload(self) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        total_chars = 0
        for message in self.messages:
            role = str(message.get("role", "unknown"))
            raw_content = message.get("content")
            content = self._serialize_payload(raw_content if raw_content is not None else "")
            total_chars += len(content)
            messages.append({"role": role, "content": self._truncate(content)})
        return {"messages": messages, "prompt_chars": total_chars}

    def _emit_model_response(
        self,
        start: float,
        *,
        phase: Literal["model_load", "loop"],
        request_id: str | None,
        status: Literal["ok", "error"],
        usage: Any | None = None,
        error: str | None = None,
        response_text: str | None = None,
    ) -> None:
        duration_ms = int((time.monotonic() - start) * 1000)
        payload: dict[str, Any] = {
            "event": "model_response",
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "phase": phase,
            "model": self._model_target,
            "status": status,
            "duration_ms": duration_ms,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        if error is not None:
            payload["error"] = error
        if usage is not None:
            payload["prompt_tokens"] = getattr(usage, "prompt_tokens", None)
            payload["completion_tokens"] = getattr(usage, "completion_tokens", None)
            payload["total_tokens"] = getattr(usage, "total_tokens", None)
        if response_text is not None:
            payload["response_chars"] = len(response_text)
            if self._include_payloads():
                payload["response_text"] = self._truncate(response_text)
        self.event_emitter.emit(payload)

    def _emit_tool_result(self, tool_name: str, result: dict[str, Any]) -> None:
        status = "error" if isinstance(result, dict) and result.get("error") else "ok"
        payload: dict[str, Any] = {
            "event": "tool_result",
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "tool_name": tool_name,
            "status": status,
        }
        if status == "error":
            error_value = result.get("error") if isinstance(result, dict) else result
            payload["error"] = str(error_value)
        if self._include_payloads():
            result_text = self._serialize_payload(result)
            payload["tool_output_chars"] = len(result_text)
            payload["tool_output"] = self._truncate(result_text)
        self.event_emitter.emit(payload)

    def _build_submit_result(self, arguments: Any) -> AgentResult:
        payload: Any = arguments
        if isinstance(arguments, str):
            try:
                payload = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        filtered = {
            key: value
            for key, value in payload.items()
            if key in {"status", "changed_files", "summary", "details", "error"}
        }
        result_data = {
            "status": filtered.get("status", "success"),
            "workspace_id": self.workspace_id,
            "changed_files": filtered.get("changed_files", []),
            "summary": filtered.get("summary", ""),
            "details": filtered.get("details", {}),
            "error": filtered.get("error"),
        }
        return AgentResult.model_validate(result_data)

    async def _dispatch_tool(self, tool_call: Any) -> str:
        tool_function = getattr(tool_call, "function", None)
        tool_name = getattr(tool_function, "name", "unknown")
        arguments = getattr(tool_function, "arguments", None)
        args: Any = arguments
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        tool_inputs = {**self._base_tool_inputs(), **args}
        self.event_emitter.emit(
            {
                "event": "tool_call",
                "agent_id": self.workspace_id,
                "node_id": self.node.node_id,
                "operation": self.definition.name,
                "tool_name": tool_name,
            }
        )
        tool_def = self.definition.tools_by_name.get(tool_name)
        if tool_def is None:
            tool_error = {"error": f"Unknown tool: {tool_name}"}
            self._emit_tool_result(tool_name, tool_error)
            return json.dumps(tool_error)

        context_parts: list[str] = []
        for provider_path in tool_def.context_providers:
            context = await self.cairn_client.run_pym(provider_path, self.workspace_id, inputs=self._base_tool_inputs())
            context_parts.append(json.dumps(context))

        result = await self.cairn_client.run_pym(tool_def.pym, self.workspace_id, inputs=tool_inputs)
        self._emit_tool_result(tool_name, result)
        content_parts = context_parts + [json.dumps(result)]
        return "\n".join(content_parts)
