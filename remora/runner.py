"""FunctionGemma runner implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Literal, Protocol, cast

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from remora.config import ServerConfig
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
        tool_schema_block = json.dumps(self.definition.tool_schemas, indent=2)
        return (
            "You have access to the following tools:\n"
            f"{tool_schema_block}\n\n"
            "Call tools by responding with JSON in the format:\n"
            '{"name": "<tool_name>", "arguments": { ... }}\n\n'
            f"{self.definition.initial_context.system_prompt}"
        )

    async def run(self) -> AgentResult:
        response_text = await self._call_model(phase="model_load")

        while self.turn_count < self.definition.max_turns:
            self.turn_count += 1
            self.messages.append(cast(ChatCompletionMessageParam, {"role": "assistant", "content": response_text}))
            tool_calls = self._parse_tool_calls(response_text)
            if not tool_calls:
                raise AgentError(
                    node_id=self.node.node_id,
                    operation=self.definition.name,
                    phase="loop",
                    error_code=AGENT_003,
                    message="Model stopped without calling submit_result",
                )
            for tool_call in tool_calls:
                name = tool_call.get("name")
                if name == "submit_result":
                    return self._build_submit_result(tool_call.get("arguments"))
                tool_result = await self._dispatch_tool(tool_call)
                tool_payload = json.dumps(tool_result)
                self.messages.append(
                    cast(
                        ChatCompletionMessageParam,
                        {"role": "user", "content": f"Tool result for {name}: {tool_payload}"},
                    )
                )
                response_text = await self._call_model(phase="loop")

        raise AgentError(
            node_id=self.node.node_id,
            operation=self.definition.name,
            phase="loop",
            error_code=AGENT_003,
            message=f"Turn limit {self.definition.max_turns} exceeded",
        )

    async def _call_model(self, *, phase: Literal["model_load", "loop"]) -> str:
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
        try:
            response = await self._http_client.chat.completions.create(
                model=self._model_target,
                messages=cast(list[ChatCompletionMessageParam], self.messages),
                max_tokens=512,
                temperature=0.1,
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
        response_text = response.choices[0].message.content or ""
        self._emit_model_response(
            start,
            phase=phase,
            request_id=request_id,
            status="ok",
            usage=response.usage,
            response_text=response_text,
        )
        return response_text

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
            content = self._serialize_payload(message.get("content", ""))
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

    def _parse_tool_calls(self, text: str) -> list[dict[str, Any]]:
        if not text:
            return []
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        results: list[dict[str, Any]] = []
        if json_blocks:
            for block in json_blocks:
                results.extend(self._coerce_tool_calls(block))
            return results
        results.extend(self._coerce_tool_calls(text))
        return results

    @staticmethod
    def _coerce_tool_calls(payload: Any) -> list[dict[str, Any]]:
        data: Any = payload
        if isinstance(payload, str):
            try:
                data = json.loads(payload.strip())
            except json.JSONDecodeError:
                return []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            return []
        return [item for item in items if isinstance(item, dict) and "name" in item]

    async def _dispatch_tool(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})
        args: Any = arguments
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        tool_name = str(name) if name is not None else "unknown"
        self.event_emitter.emit(
            {
                "event": "tool_call",
                "agent_id": self.workspace_id,
                "node_id": self.node.node_id,
                "operation": self.definition.name,
                "tool_name": tool_name,
            }
        )
        tool_def = self.definition.tools_by_name.get(str(name)) if name is not None else None
        if tool_def is None:
            tool_error = {"error": f"Unknown tool: {name}"}
            self._emit_tool_result(tool_name, tool_error)
            return tool_error

        for provider_path in tool_def.context_providers:
            context = await self.cairn_client.run_pym(provider_path, self.workspace_id, inputs={})
            self.messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "role": "user",
                        "content": f"[Context] {context}",
                    },
                )
            )

        result = await self.cairn_client.run_pym(tool_def.pym, self.workspace_id, inputs=args)
        self._emit_tool_result(tool_name, result)
        return result
