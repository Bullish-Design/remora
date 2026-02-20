"""FunctionGemma runner implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from pydantic import ValidationError
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam, ChatCompletionToolParam


from remora.config import RunnerConfig, ServerConfig
from remora.context import ContextManager, get_hub_client
from remora.context.summarizers import get_default_summarizers
from remora.discovery import CSTNode
from remora.events import EventEmitter, EventName, EventStatus, NullEventEmitter
from remora.errors import AGENT_002, AGENT_003, AGENT_004
from remora.results import AgentResult, AgentStatus
from remora.subagent import SUBMIT_RESULT_TOOL, SubagentDefinition
from remora.tool_parser import ParsedToolCall, parse_tool_call_from_content

if TYPE_CHECKING:
    from remora.execution import SnapshotManager
    from remora.orchestrator import RemoraAgentContext

logger = logging.getLogger(__name__)


def _missing_identifier(label: str) -> str:
    return f"missing-{label}-{uuid.uuid4().hex[:8]}"


class GrailExecutor(Protocol):
    """Protocol for in-process Grail script execution."""

    async def execute(
        self,
        pym_path: Path,
        grail_dir: Path,
        inputs: dict[str, Any],
        limits: dict[str, Any] | None = None,
        agent_id: str | None = None,
        workspace_path: Path | None = None,
        stable_path: Path | None = None,
        node_source: str | None = None,
        node_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


from cairn.utils.retry import RetryStrategy


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
    """Run a function-calling agent loop for one CST node.

    Args:
        definition: Subagent configuration and tool catalog.
        node: Discovered CST node to operate on.
        ctx: Context for this agent run.
    """

    definition: SubagentDefinition
    node: CSTNode
    ctx: RemoraAgentContext

    server_config: ServerConfig
    runner_config: RunnerConfig
    adapter_name: str | None = None
    http_client: AsyncOpenAI | None = None
    event_emitter: EventEmitter = field(default_factory=NullEventEmitter)
    grail_executor: GrailExecutor | None = None
    grail_dir: Path | None = None
    grail_limits: dict[str, Any] | None = None
    workspace_root: Path | None = None
    stable_root: Path | None = None
    snapshot_manager: SnapshotManager | None = None
    context_manager: ContextManager = field(init=False)
    messages: list[ChatCompletionMessageParam] = field(init=False)
    turn_count: int = field(init=False)
    _http_client: AsyncOpenAI = field(init=False)
    _system_prompt: str = field(init=False)
    _initial_message: str = field(init=False)
    _model_target: str = field(init=False)
    _retry: RetryStrategy = field(init=False)
    _cached_system_prompt: str | None = field(init=False)

    @property
    def workspace_id(self) -> str:
        """Backward-compatible alias — returns ``ctx.agent_id``."""
        return self.ctx.agent_id

    def __post_init__(self) -> None:
        self._http_client = self.http_client or AsyncOpenAI(
            base_url=self.server_config.base_url,
            api_key=self.server_config.api_key,
            timeout=self.server_config.timeout,
        )
        self._model_target = self.adapter_name or self.server_config.default_adapter
        self._system_prompt = self.definition.initial_context.system_prompt
        self._initial_message = self.definition.initial_context.render(self.node)
        self.context_manager = ContextManager(
            {
                "agent_id": self.ctx.agent_id,
                "goal": f"{self.definition.name} on {self.node.name}",
                "operation": self.definition.name,
                "node_id": self.node.node_id,
                "node_summary": self._summarize_node(),
            },
            summarizers=get_default_summarizers(),
        )
        self.context_manager.set_hub_client(get_hub_client())
        self.messages = []
        self.turn_count = 0
        self.messages.append(cast(ChatCompletionMessageParam, {"role": "system", "content": self._system_prompt}))
        self.messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": self._initial_message}))

        self._cached_system_prompt = None
        if not self.runner_config.include_prompt_context:
            self._cached_system_prompt = self._build_system_prompt(None)

        # Configure retry strategy from config
        retry_config = self.server_config.retry
        self._retry = RetryStrategy(
            max_attempts=retry_config.max_attempts,
            initial_delay=retry_config.initial_delay,
            max_delay=retry_config.max_delay,
            backoff_factor=retry_config.backoff_factor,
        )
        logger.info(
            "Runner initialized for %s (model=%s, turns=%d)",
            self.workspace_id,
            self._model_target,
            self.definition.max_turns,
        )

    def _build_system_prompt(self, prompt_context: dict[str, Any] | None = None) -> str:
        base_prompt = self._system_prompt
        tool_guide = self._build_tool_guide() if self.runner_config.include_tool_guide else ""
        if not prompt_context:
            prompt_lines = [base_prompt]
            if tool_guide:
                prompt_lines.extend(["", tool_guide])
            return "\n".join(prompt_lines).strip()

        recent_actions = self._format_recent_actions(prompt_context.get("recent_actions", []))
        knowledge = self._format_knowledge(prompt_context.get("knowledge", {}))
        lines = [base_prompt]
        if tool_guide:
            lines.extend(["", tool_guide])
        lines.extend(
            [
                "",
                "## Current State",
                f"Goal: {prompt_context.get('goal', '')}",
                f"Operation: {prompt_context.get('operation', '')}",
                f"Target: {prompt_context.get('node_id', '')}",
                f"Turn: {prompt_context.get('turn', 0)}",
            ]
        )
        node_summary = prompt_context.get("node_summary", "")
        if node_summary:
            lines.append(f"Node Summary: {node_summary}")
        lines.extend(
            [
                "",
                "## Recent Actions",
                recent_actions,
                "",
                "## Working Knowledge",
                knowledge,
            ]
        )
        last_error = prompt_context.get("last_error")
        if last_error:
            lines.extend(["", "## Last Error", str(last_error)])
        hub_context = prompt_context.get("hub_context")
        if hub_context:
            lines.extend(["", "## Hub Context", self._format_knowledge(hub_context)])
        return "\n".join(lines).strip()

    def _summarize_node(self) -> str:
        node = self.node
        return f"{node.node_type.value} '{node.name}' in {node.file_path.name}"

    def _build_tool_guide(self) -> str:
        schemas = self.definition.tool_schemas
        if not schemas:
            return ""
        lines = ["Tools:"]
        for schema in schemas:
            function = schema.get("function", {})
            name = function.get("name", "unknown")
            description = str(function.get("description", "")).strip()
            parameters = function.get("parameters", {})
            required = parameters.get("required") or []
            required_list = ", ".join(required) if required else "none"
            if description:
                lines.append(f"- {name}: {description} (required: {required_list})")
            else:
                lines.append(f"- {name} (required: {required_list})")
        return "\n".join(lines)

    def _format_recent_actions(self, actions: list[dict[str, Any]]) -> str:
        if not actions:
            return "None"
        lines = []
        for action in actions:
            tool = action.get("tool", "unknown")
            summary = action.get("summary", "")
            outcome = action.get("outcome", "")
            lines.append(f"- {tool}: {summary} ({outcome})")
        return "\n".join(lines)

    def _format_knowledge(self, knowledge: dict[str, Any]) -> str:
        if not knowledge:
            return "None"
        try:
            return json.dumps(knowledge, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(knowledge)

    def _build_prompt_messages(self) -> list[ChatCompletionMessageParam]:
        """Return the full accumulated conversation history.

        The system prompt (messages[0]) is updated in-place if include_prompt_context
        is enabled, allowing dynamic context injection while preserving history.
        """
        if self._cached_system_prompt is not None:
            system_content = self._cached_system_prompt
        else:
            prompt_context = self.context_manager.get_prompt_context()
            system_content = self._build_system_prompt(prompt_context)

        self.messages[0] = cast(
            ChatCompletionMessageParam,
            {"role": "system", "content": system_content},
        )

        return list(self.messages)

    def _trim_history_if_needed(self, max_messages: int = 50) -> None:
        """Trim conversation history to prevent context overflow.

        Keeps the system prompt and the most recent messages. This is a
        simple sliding window approach — more sophisticated summarization
        could be added later.

        Args:
            max_messages: Maximum number of messages to retain.
        """
        if len(self.messages) <= max_messages:
            return

        system_message = self.messages[0]
        recent_messages = self.messages[-(max_messages - 1) :]
        self.messages = [system_message] + recent_messages

        logger.debug("Trimmed conversation history to %d messages", len(self.messages))

    async def run(self) -> AgentResult:
        """Execute the model loop until a result is produced."""
        await self.context_manager.pull_hub_context()
        message = await self._call_model(phase="model_load", tool_choice=self._tool_choice_for_turn(1))

        while self.turn_count < self.definition.max_turns:
            self.turn_count += 1
            self.context_manager.increment_turn()
            self._trim_history_if_needed(max_messages=40)
            self.messages.append(self._coerce_message_param(message))
            tool_calls = message.tool_calls or []
            if not tool_calls:
                result = await self._handle_no_tool_calls(message)
                if result is not None:
                    return result
                await self.context_manager.pull_hub_context()
                next_turn = self.turn_count + 1
                message = await self._call_model(
                    phase="loop",
                    tool_choice=self._tool_choice_for_turn(next_turn),
                )
                continue
            for tool_call in tool_calls:
                tool_function = getattr(tool_call, "function", None)
                name = getattr(tool_function, "name", None)
                if name == SUBMIT_RESULT_TOOL:
                    return self._build_submit_result(getattr(tool_function, "arguments", None))
                tool_result_content = await self._dispatch_tool(tool_call)
                tool_call_id = getattr(tool_call, "id", None) or _missing_identifier("tool-call")
                tool_name = name or _missing_identifier("tool-name")
                self._apply_tool_result_event(tool_name, tool_result_content)
                self.messages.append(
                    cast(
                        ChatCompletionMessageParam,
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": tool_result_content,
                        },
                    )
                )
            await self.context_manager.pull_hub_context()
            next_turn = self.turn_count + 1
            message = await self._call_model(phase="loop", tool_choice=self._tool_choice_for_turn(next_turn))

        raise AgentError(
            node_id=self.node.node_id,
            operation=self.definition.name,
            phase="loop",
            error_code=AGENT_004,
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
        prompt_messages = self._build_prompt_messages()
        payload: dict[str, Any] = {
            "event": EventName.MODEL_REQUEST,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "phase": "execution",
            "step": phase,
            "model": self._model_target,
        }
        if self._include_payloads():
            payload.update(self._build_message_payload(prompt_messages))
        self.event_emitter.emit(payload)
        if tool_choice is None:
            tool_choice = self.runner_config.tool_choice

        # Filter out system-injected inputs from the schema sent to the model
        raw_tools = self.definition.tool_schemas
        tools_payload = []
        for tool in raw_tools:
            # excessive copying to avoid mutating original
            tool_copy = json.loads(json.dumps(tool))
            tool_params = tool_copy.get("function", {}).get("parameters", {})
            properties = tool_params.get("properties", {})
            required = tool_params.get("required", [])

            # Keys to remove
            for key in ["node_text", "target_file", "workspace_id", "node_text_input", "target_file_input"]:
                if key in properties:
                    del properties[key]
                if key in required:
                    required.remove(key)

            tools_payload.append(tool_copy)

        self._emit_tool_debug("model_tools_before", tool_choice)
        self._emit_request_debug(
            model=self._model_target,
            tool_choice=tool_choice,
            tools=tools_payload,
            messages=prompt_messages,
        )
        logger.debug(
            "Calling model %s (phase=%s, turn=%d, messages=%d)",
            self._model_target,
            phase,
            self.turn_count,
            len(prompt_messages),
        )

        async def _attempt() -> Any:
            return await self._http_client.chat.completions.create(
                model=self._model_target,
                messages=cast(list[ChatCompletionMessageParam], prompt_messages),
                tools=cast(list[ChatCompletionToolParam], tools_payload),
                tool_choice=cast(Any, tool_choice),
                max_tokens=self.runner_config.max_tokens,
                temperature=self.runner_config.temperature,
            )

        try:
            response = await self._retry.with_retry(
                operation=_attempt,
                retry_exceptions=(APIConnectionError, APITimeoutError),
            )
            request_id = getattr(response, "id", None)
        except Exception as exc:
            self._emit_model_response(
                start,
                phase=phase,
                request_id=request_id,
                status=EventStatus.ERROR,
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
            status=EventStatus.OK,
            usage=getattr(response, "usage", None),
            response_text=response_text,
        )
        logger.debug(
            "Model response (phase=%s, request_id=%s, tool_calls=%d)",
            phase,
            request_id,
            len(message.tool_calls or []),
        )
        return message

    def _coerce_message_param(self, message: ChatCompletionMessage) -> ChatCompletionMessageParam:
        return cast(ChatCompletionMessageParam, message.model_dump(exclude_none=True))

    def _tool_choice_for_turn(self, next_turn: int) -> Any:
        return self.runner_config.tool_choice

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

    async def _handle_no_tool_calls(self, message: ChatCompletionMessage) -> AgentResult | None:
        """Handle a model response with no structured tool_calls.

        Attempts to parse tool calls from JSON content. If parsing fails
        and tool_choice is "required", raises an error. Otherwise, treats
        the content as a final result.
        """
        content = message.content or ""

        parsed_call = parse_tool_call_from_content(content)
        if parsed_call is not None:
            return await self._dispatch_parsed_tool_call(parsed_call)

        if self.runner_config.tool_choice == "required":
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase="loop",
                error_code=AGENT_003,
                message=f"Model stopped without calling {SUBMIT_RESULT_TOOL}",
            )

        if content:
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    return self._build_submit_result(parsed)
            except json.JSONDecodeError:
                pass

        result_data = {
            "status": AgentStatus.SUCCESS,
            "workspace_id": self.workspace_id,
            "changed_files": [],
            "summary": content,
            "details": {},
            "error": None,
        }
        return AgentResult.model_validate(result_data)

    async def _dispatch_parsed_tool_call(self, parsed_call: ParsedToolCall) -> AgentResult | None:
        """Dispatch a tool call parsed from JSON content.

        This method handles tool calls that were extracted from message.content
        instead of message.tool_calls. It synthesizes the necessary fields and
        delegates to the standard dispatch flow.
        """
        tool_name = parsed_call.name
        arguments = parsed_call.arguments

        if tool_name == SUBMIT_RESULT_TOOL:
            return self._build_submit_result(arguments)

        self.event_emitter.emit(
            {
                "event": EventName.TOOL_CALL,
                "agent_id": self.workspace_id,
                "node_id": self.node.node_id,
                "operation": self.definition.name,
                "tool_name": tool_name,
                "phase": "execution",
                "status": EventStatus.OK,
                "parsed_from_content": True,
            }
        )

        tool_inputs = {**self._base_tool_inputs(), **arguments}

        tool_def = self.definition.tools_by_name.get(tool_name)
        if tool_def is None:
            tool_error = {"error": f"Unknown tool: {tool_name}"}
            self._emit_tool_result(tool_name, tool_error)
            self.messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "role": "tool",
                        "tool_call_id": parsed_call.id,
                        "name": tool_name,
                        "content": json.dumps(tool_error),
                    },
                )
            )
            return None

        if self.grail_executor is not None and self.grail_dir is not None:
            tool_result_content = await self._dispatch_tool_grail(
                tool_name,
                tool_def,
                tool_inputs,
            )
        else:
            tool_result_content = json.dumps({"error": "No execution backend configured"})

        self._apply_tool_result_event(tool_name, tool_result_content)

        self.messages.append(
            cast(
                ChatCompletionMessageParam,
                {
                    "role": "tool",
                    "tool_call_id": parsed_call.id,
                    "name": tool_name,
                    "content": tool_result_content,
                },
            )
        )

        return None

    def _apply_tool_result_event(self, tool_name: str, result_content: Any) -> None:
        data = self._parse_tool_result_content(result_content)
        self.context_manager.apply_event(
            {
                "type": "tool_result",
                "tool_name": tool_name,
                "data": data,
            }
        )

    def _parse_tool_result_content(self, result_content: Any) -> dict[str, Any]:
        """Parse tool result content into a dict.

        Tries to parse the entire content as JSON first, then falls back
        to extracting JSON from the last non-empty line.
        """
        if isinstance(result_content, dict):
            return result_content

        if not result_content:
            return {}

        if not isinstance(result_content, str):
            return {"raw_output": result_content}

        content = result_content.strip()
        if not content:
            return {}

        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            return {"raw_output": data}
        except json.JSONDecodeError:
            pass

        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            return {}

        try:
            data = json.loads(lines[-1])
            if isinstance(data, dict):
                return data
            return {"raw_output": data}
        except json.JSONDecodeError:
            return {"raw_output": content}

    def _emit_tool_debug(self, event: str, tool_choice: Any, *, request_id: str | None = None) -> None:
        tools = self.definition.tool_schemas
        payload: dict[str, Any] = {
            "event": event,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "phase": "execution",
            "model": self._model_target,
            "tool_count": len(tools),
            "tool_choice": tool_choice,
        }

        if request_id is not None:
            payload["request_id"] = request_id
        if self._include_payloads():
            tools_text = self._serialize_payload(tools)
            payload["tools_chars"] = len(tools_text)
            payload["tools"] = self._truncate(tools_text)
        self.event_emitter.emit(payload)

    def _emit_request_debug(
        self,
        *,
        model: str,
        tool_choice: Any,
        tools: list[dict[str, Any]],
        messages: list[ChatCompletionMessageParam],
    ) -> None:
        payload: dict[str, Any] = {
            "event": EventName.MODEL_REQUEST_DEBUG,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "phase": "execution",
            "model": model,
            "tool_choice": tool_choice,
            "tools_count": len(tools),
        }
        if self._include_payloads():
            messages_text = self._serialize_payload(messages)
            tools_text = self._serialize_payload(tools)
            request_payload = {
                "model": model,
                "messages": messages,
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

    def _build_message_payload(self, prompt_messages: list[ChatCompletionMessageParam]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        total_chars = 0
        for message in prompt_messages:
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
            "event": EventName.MODEL_RESPONSE,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "phase": "execution",
            "step": phase,
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

    def _emit_tool_result(self, tool_name: str, result: Any) -> None:
        status = EventStatus.OK
        if isinstance(result, dict) and (result.get("outcome") == "error" or result.get("error")):
            status = EventStatus.ERROR
        payload: dict[str, Any] = {
            "event": EventName.TOOL_RESULT,
            "agent_id": self.workspace_id,
            "node_id": self.node.node_id,
            "operation": self.definition.name,
            "tool_name": tool_name,
            "phase": "execution",
            "status": status,
        }
        if status == EventStatus.ERROR:
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
        status_raw = filtered.get("status", AgentStatus.SUCCESS)
        if status_raw not in {AgentStatus.SUCCESS, AgentStatus.FAILED, AgentStatus.SKIPPED}:
            status_raw = AgentStatus.SUCCESS
        details = filtered.get("details", {})
        if not isinstance(details, dict):
            details = {}
        if self.definition.grail_summary:
            details.setdefault("grail_check", self.definition.grail_summary)
        result_data = {
            "status": status_raw,
            "workspace_id": self.workspace_id,
            "changed_files": filtered.get("changed_files", []),
            "summary": filtered.get("summary", ""),
            "details": details,
            "error": filtered.get("error"),
        }
        try:
            result = AgentResult.model_validate(result_data)
        except ValidationError as exc:
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase="merge",
                error_code=AGENT_003,
                message=f"submit_result payload failed validation: {exc}",
            ) from exc
        self.event_emitter.emit(
            {
                "event": EventName.SUBMIT_RESULT,
                "agent_id": self.workspace_id,
                "node_id": self.node.node_id,
                "operation": self.definition.name,
                "phase": "submission",
                "status": result.status,
            }
        )
        logger.info("Agent %s submitted result: status=%s", self.workspace_id, result.status)
        return result

    async def _dispatch_tool(self, tool_call: Any) -> str:
        tool_function = getattr(tool_call, "function", None)
        tool_name = getattr(tool_function, "name", None) or _missing_identifier("tool-name")
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
        logger.debug("Dispatching tool %s for %s", tool_name, self.workspace_id)
        self.event_emitter.emit(
            {
                "event": EventName.TOOL_CALL,
                "agent_id": self.workspace_id,
                "node_id": self.node.node_id,
                "operation": self.definition.name,
                "tool_name": tool_name,
                "phase": "execution",
                "status": EventStatus.OK,
            }
        )

        # Built-in: resume a suspended snapshot
        if tool_name == "resume_tool":
            return await self._handle_resume(args)

        tool_def = self.definition.tools_by_name.get(tool_name)
        if tool_def is None:
            tool_error = {"error": f"Unknown tool: {tool_name}"}
            self._emit_tool_result(tool_name, tool_error)
            return json.dumps(tool_error)

        # --- In-process execution via GrailExecutor ---
        if self.grail_executor is not None and self.grail_dir is not None:
            return await self._dispatch_tool_grail(
                tool_name,
                tool_def,
                tool_inputs,
            )

        # If we get here, no executor is configured
        tool_error = {"error": "No execution backend configured"}
        self._emit_tool_result(tool_name, tool_error)
        return json.dumps(tool_error)

    async def _dispatch_tool_grail(
        self,
        tool_name: str,
        tool_def: Any,
        tool_inputs: dict[str, Any],
    ) -> str:
        """Execute a tool via GrailScript.run() in a child process."""
        assert self.grail_executor is not None
        assert self.grail_dir is not None

        context_parts, error = await self._run_context_providers(tool_name, tool_def)
        if error is not None:
            self._emit_tool_result(tool_name, error)
            return json.dumps(error)

        result = await self._execute_grail_script(tool_def.pym, tool_inputs)
        if result.get("error"):
            self._emit_tool_result(tool_name, result)
            return json.dumps(result)
        tool_result = result.get("result", {})
        self._emit_tool_result(tool_name, tool_result)
        content_parts = context_parts + [json.dumps(tool_result)]
        return "\n".join(content_parts)

    async def _run_context_providers(self, tool_name: str, tool_def: Any) -> tuple[list[str], dict[str, Any] | None]:
        """Execute context providers for a tool.

        Args:
            tool_name: Tool name for logging context.
            tool_def: Tool definition containing context providers.

        Returns:
            A list of serialized context outputs and an optional error payload.
        """
        context_parts: list[str] = []
        for provider_path in tool_def.context_providers:
            result = await self._execute_grail_script(provider_path, self._base_tool_inputs())
            if result.get("error"):
                return [], result
            context_parts.append(json.dumps(result.get("result", {})))
        return context_parts, None

    async def _execute_grail_script(self, pym_path: Path, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a grail script with shared metadata."""
        assert self.grail_executor is not None
        assert self.grail_dir is not None
        return await self.grail_executor.execute(
            pym_path=pym_path,
            grail_dir=self.grail_dir,
            inputs=inputs,
            limits=self.grail_limits,
            agent_id=self.ctx.agent_id,
            workspace_path=self.workspace_root,
            stable_path=self.stable_root,
            node_source=self.node.text,
            node_metadata={
                "name": self.node.name,
                "type": self.node.node_type,
                "file_path": str(self.node.file_path),
                "node_id": self.node.node_id,
            },
        )

    async def _handle_resume(self, args: dict[str, Any]) -> str:
        """Handle a ``resume_tool`` call from the model."""
        if self.snapshot_manager is None:
            result = {
                "error": True,
                "code": "SNAPSHOTS_DISABLED",
                "message": "Snapshot pause/resume is not enabled",
            }
            self._emit_tool_result("resume_tool", result)
            return json.dumps(result)

        snapshot_id = args.get("snapshot_id", "")
        additional_context = args.get("additional_context")
        result = self.snapshot_manager.resume_script(
            snapshot_id=snapshot_id,
            return_value=additional_context,
        )
        self._emit_tool_result("resume_tool", result)
        if result.get("suspended"):
            logger.info(
                "Snapshot %s still suspended (resume %d)",
                snapshot_id,
                result.get("resume_count", 0),
            )
        return json.dumps(result)
