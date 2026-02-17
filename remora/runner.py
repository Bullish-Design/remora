"""FunctionGemma runner implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
from functools import partial
import json
import threading
from typing import Any, Literal, Protocol

from remora.discovery import CSTNode
from remora.errors import AGENT_002, AGENT_003
from remora.results import AgentResult
from remora.subagent import SubagentDefinition

try:
    from llama_cpp import Llama
except ImportError:  # pragma: no cover - optional dependency in tests

    class Llama:  # type: ignore[no-redef]
        def __init__(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("llama-cpp-python is required to load GGUF models.")


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


class ModelCache:
    _instances: dict[str, Llama] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, model_path: str, **kwargs: Any) -> Llama:
        with cls._lock:
            if model_path not in cls._instances:
                cls._instances[model_path] = Llama(model_path=model_path, **kwargs)
            return cls._instances[model_path]

    @classmethod
    def clear(cls) -> None:
        """For testing: clear all cached instances."""
        with cls._lock:
            cls._instances.clear()


@dataclass
class FunctionGemmaRunner:
    definition: SubagentDefinition
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient
    model: Llama = field(init=False)
    messages: list[dict[str, Any]] = field(init=False)
    turn_count: int = field(init=False)

    def __post_init__(self) -> None:
        if not self.definition.model.exists():
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase="model_load",
                error_code=AGENT_002,
                message=f"GGUF not found: {self.definition.model}",
            )
        self.model = ModelCache.get(
            str(self.definition.model),
            n_ctx=4096,
            n_threads=2,
            verbose=False,
            n_gpu_layers=0,
        )
        self.messages = []
        self.turn_count = 0
        self._build_initial_messages()

    def _build_initial_messages(self) -> None:
        self.messages = [
            {
                "role": "system",
                "content": self.definition.initial_context.system_prompt,
            },
            {
                "role": "user",
                "content": self.definition.initial_context.render(self.node),
            },
        ]

    async def run(self) -> AgentResult:
        while self.turn_count < self.definition.max_turns:
            response = await self._call_model()
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            self.messages.append(message)
            self.turn_count += 1

            finish_reason = choice.get("finish_reason")
            if finish_reason == "stop":
                summary = message.get("content", "") if isinstance(message, dict) else ""
                return AgentResult(
                    status="success",
                    workspace_id=self.workspace_id,
                    changed_files=[],
                    summary=summary,
                    details={},
                    error=None,
                )

            if finish_reason == "tool_calls":
                tool_calls = message.get("tool_calls", []) if isinstance(message, dict) else []
                for tool_call in tool_calls:
                    result = await self._dispatch_tool(tool_call)
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", ""),
                            "content": json.dumps(result),
                        }
                    )
                    if tool_call.get("function", {}).get("name") == "submit_result":
                        arguments = tool_call.get("function", {}).get("arguments", "{}")
                        return self._build_submit_result(arguments)
                continue

            summary = message.get("content", "") if isinstance(message, dict) else ""
            return AgentResult(
                status="success",
                workspace_id=self.workspace_id,
                changed_files=[],
                summary=summary,
                details={},
                error=None,
            )

        return AgentResult(
            status="failed",
            workspace_id=self.workspace_id,
            changed_files=[],
            summary="",
            details={},
            error=f"{AGENT_003}: Turn limit ({self.definition.max_turns}) exceeded",
        )

    async def _call_model(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        call = partial(
            self.model.create_chat_completion,
            messages=self.messages,
            tools=self.definition.tool_schemas,
            tool_choice="auto",
        )
        return await loop.run_in_executor(None, call)

    def _build_submit_result(self, arguments: str) -> AgentResult:
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

    async def _dispatch_tool(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        name = tool_call.get("function", {}).get("name")
        arguments = tool_call.get("function", {}).get("arguments", "{}")
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
                {
                    "role": "user",
                    "content": f"[Context] {context}",
                }
            )

        return await self.cairn_client.run_pym(tool_def.pym, self.workspace_id, inputs=args)
