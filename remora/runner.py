"""FunctionGemma runner implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from typing import Any, Literal, Protocol, cast

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from remora.config import ServerConfig
from remora.discovery import CSTNode
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
        try:
            response = await self._http_client.chat.completions.create(
                model=self._model_target,
                messages=cast(list[ChatCompletionMessageParam], self.messages),
                max_tokens=512,
                temperature=0.1,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase=phase,
                error_code=AGENT_002,
                message=f"Cannot reach vLLM server at {self.server_config.base_url}",
            ) from exc
        return response.choices[0].message.content or ""

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
        tool_def = self.definition.tools_by_name.get(str(name)) if name is not None else None
        if tool_def is None:
            return {"error": f"Unknown tool: {name}"}

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

        return await self.cairn_client.run_pym(tool_def.pym, self.workspace_id, inputs=args)
