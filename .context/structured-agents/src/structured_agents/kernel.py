"""AgentKernel - the core agent loop orchestrator."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence, cast

from structured_agents.client.factory import build_client
from structured_agents.client.protocol import LLMClient
from structured_agents.exceptions import KernelError
from structured_agents.grammar.config import GrammarConfig
from structured_agents.history import HistoryStrategy, SlidingWindowHistory
from structured_agents.observer import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    NullObserver,
    Observer,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.plugins.protocol import ModelPlugin
from structured_agents.tool_sources import ContextProvider, ToolSource
from structured_agents.types import (
    KernelConfig,
    Message,
    RunResult,
    StepResult,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSchema,
)

logger = logging.getLogger(__name__)

TerminationCondition = Callable[[ToolResult], bool]


@dataclass
class AgentKernel:
    """The core agent loop orchestrator.

    The kernel handles:
    - Making model calls with appropriate formatting
    - Parsing responses and extracting tool calls
    - Executing tools via the backend
    - Managing conversation history
    - Emitting events to observers

    It does NOT handle:
    - Workspace management (that's the consumer's responsibility)
    - Multi-agent orchestration (that's Remora's job)
    - External state management (that's the consumer's job)
    """

    config: KernelConfig
    plugin: ModelPlugin
    tool_source: ToolSource
    observer: Observer = field(default_factory=NullObserver)
    history_strategy: HistoryStrategy = field(default_factory=SlidingWindowHistory)
    max_history_messages: int = 50
    grammar_config: GrammarConfig = field(default_factory=GrammarConfig)
    client: LLMClient | None = None
    _client: LLMClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.tool_source is None:
            raise KernelError("Tool source is required for kernel execution.")
        self._client = self.client or build_client(self.config)
        self._validate_grammar_config()

    def _validate_grammar_config(self) -> None:
        mode = self.grammar_config.mode
        if mode == "ebnf" and not self.plugin.supports_ebnf:
            raise KernelError("Plugin does not support EBNF grammar mode.")
        if mode == "structural_tag" and not self.plugin.supports_structural_tags:
            raise KernelError("Plugin does not support structural tag mode.")
        if mode == "json_schema" and not self.plugin.supports_json_schema:
            raise KernelError("Plugin does not support JSON schema mode.")

    def _resolve_tools(
        self, tools: Sequence[ToolSchema] | Sequence[str]
    ) -> list[ToolSchema]:
        if not tools:
            return []
        if isinstance(tools[0], ToolSchema):
            return list(cast(Sequence[ToolSchema], tools))
        tool_names = list(cast(Sequence[str], tools))
        return self.tool_source.resolve_all(tool_names)

    async def _build_context(
        self, context_provider: ContextProvider | None
    ) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if context_provider:
            context = await context_provider()
        for provider in self.tool_source.context_providers():
            provider_context = await provider()
            context.update(provider_context)
        return context

    async def step(
        self,
        messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        context: dict[str, Any] | None = None,
        turn: int = 1,
    ) -> StepResult:
        """Execute a single turn: model call + tool execution.

        Args:
            messages: Current conversation history.
            tools: Available tool schemas.
            context: Per-step context to pass to tool execution.
            turn: Current turn number (for events).

        Returns:
            StepResult with response, tool calls, and results.
        """
        context = context or {}

        resolved_tools = self._resolve_tools(tools)

        formatted_messages = self.plugin.format_messages(messages, resolved_tools)
        formatted_tools = (
            self.plugin.format_tools(resolved_tools) if resolved_tools else None
        )

        grammar = (
            self.plugin.build_grammar(resolved_tools, self.grammar_config)
            if resolved_tools
            else None
        )
        extra_body = self.plugin.to_extra_body(grammar)

        await self.observer.on_model_request(
            ModelRequestEvent(
                turn=turn,
                messages_count=len(messages),
                tools_count=len(resolved_tools),
                model=self.config.model,
            )
        )

        start_time = time.monotonic()
        response = await self._client.chat_completion(
            messages=formatted_messages,
            tools=formatted_tools,
            tool_choice=self.config.tool_choice if resolved_tools else "none",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            extra_body=extra_body,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        content, tool_calls = self.plugin.parse_response(
            response.content,
            response.tool_calls,
        )

        await self.observer.on_model_response(
            ModelResponseEvent(
                turn=turn,
                duration_ms=duration_ms,
                content=content,
                tool_calls_count=len(tool_calls),
                usage=response.usage,
            )
        )

        response_message = Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )

        tool_results: list[ToolResult | None] = [None] * len(tool_calls)
        tool_result_events: list[ToolResultEvent | None] = [None] * len(tool_calls)
        execution_plan: list[tuple[int, ToolCall, ToolSchema]] = []

        for index, tool_call in enumerate(tool_calls):
            tool_schema = next(
                (tool for tool in resolved_tools if tool.name == tool_call.name),
                None,
            )

            if not tool_schema:
                tool_results[index] = ToolResult(
                    call_id=tool_call.id,
                    name=tool_call.name,
                    output=f"Unknown tool: {tool_call.name}",
                    is_error=True,
                )
                continue

            await self.observer.on_tool_call(
                ToolCallEvent(
                    turn=turn,
                    tool_name=tool_call.name,
                    call_id=tool_call.id,
                    arguments=tool_call.arguments,
                )
            )
            execution_plan.append((index, tool_call, tool_schema))

        async def execute_tool(
            tool_call: ToolCall, tool_schema: ToolSchema
        ) -> tuple[ToolResult, int, str]:
            tool_start = time.monotonic()
            result = await self.tool_source.execute(tool_call, tool_schema, context)
            tool_duration_ms = int((time.monotonic() - tool_start) * 1000)
            output_preview = (
                str(result.output)[:200] if result.output is not None else ""
            )
            return result, tool_duration_ms, output_preview

        strategy = self.config.tool_execution_strategy
        if (
            strategy.mode == "sequential"
            or strategy.max_concurrency <= 1
            or len(execution_plan) <= 1
        ):
            for index, tool_call, tool_schema in execution_plan:
                result, tool_duration_ms, output_preview = await execute_tool(
                    tool_call, tool_schema
                )
                tool_results[index] = result
                tool_result_events[index] = ToolResultEvent(
                    turn=turn,
                    tool_name=tool_call.name,
                    call_id=tool_call.id,
                    is_error=result.is_error,
                    duration_ms=tool_duration_ms,
                    output_preview=output_preview,
                )
        else:
            semaphore = asyncio.Semaphore(strategy.max_concurrency)

            async def execute_with_semaphore(
                tool_call: ToolCall, tool_schema: ToolSchema
            ) -> tuple[ToolResult, int, str]:
                async with semaphore:
                    return await execute_tool(tool_call, tool_schema)

            tasks = [
                asyncio.create_task(execute_with_semaphore(tool_call, tool_schema))
                for _, tool_call, tool_schema in execution_plan
            ]
            task_results = await asyncio.gather(*tasks)

            for (index, tool_call, _), (
                result,
                tool_duration_ms,
                output_preview,
            ) in zip(execution_plan, task_results):
                tool_results[index] = result
                tool_result_events[index] = ToolResultEvent(
                    turn=turn,
                    tool_name=tool_call.name,
                    call_id=tool_call.id,
                    is_error=result.is_error,
                    duration_ms=tool_duration_ms,
                    output_preview=output_preview,
                )

        for event in tool_result_events:
            if event is not None:
                await self.observer.on_tool_result(event)

        ordered_results = [result for result in tool_results if result is not None]

        return StepResult(
            response_message=response_message,
            tool_calls=tool_calls,
            tool_results=ordered_results,
            usage=response.usage,
        )

    async def run(
        self,
        initial_messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        *,
        max_turns: int = 20,
        termination: TerminationCondition | None = None,
        context_provider: ContextProvider | None = None,
    ) -> RunResult:
        """Execute the full agent loop until termination.

        Args:
            initial_messages: Starting conversation (system prompt + user message).
            tools: Available tool schemas.
            max_turns: Maximum iterations before forced stop.
            termination: Optional function that returns True when a tool result
                should terminate the loop (e.g., submit_result tool).
            context_provider: Optional async function to provide per-turn context.

        Returns:
            RunResult with final state and conversation history.
        """
        messages = list(initial_messages)
        turn_count = 0
        final_tool_result: ToolResult | None = None
        termination_reason = "max_turns"
        total_usage = TokenUsage(0, 0, 0)

        start_time = time.monotonic()
        resolved_tools = self._resolve_tools(tools)

        await self.observer.on_kernel_start(
            KernelStartEvent(
                max_turns=max_turns,
                tools_count=len(resolved_tools),
                initial_messages_count=len(initial_messages),
            )
        )

        try:
            while turn_count < max_turns:
                turn_count += 1

                context = await self._build_context(context_provider)

                messages = self.history_strategy.trim(
                    messages, self.max_history_messages
                )

                step_result = await self.step(
                    messages=messages,
                    tools=resolved_tools,
                    context=context,
                    turn=turn_count,
                )

                if step_result.usage:
                    total_usage = TokenUsage(
                        prompt_tokens=total_usage.prompt_tokens
                        + step_result.usage.prompt_tokens,
                        completion_tokens=total_usage.completion_tokens
                        + step_result.usage.completion_tokens,
                        total_tokens=total_usage.total_tokens
                        + step_result.usage.total_tokens,
                    )

                messages.append(step_result.response_message)

                for result in step_result.tool_results:
                    messages.append(result.to_message())

                errors_count = sum(
                    1 for result in step_result.tool_results if result.is_error
                )

                await self.observer.on_turn_complete(
                    TurnCompleteEvent(
                        turn=turn_count,
                        tool_calls_count=len(step_result.tool_calls),
                        tool_results_count=len(step_result.tool_results),
                        errors_count=errors_count,
                    )
                )

                if termination:
                    for result in step_result.tool_results:
                        if termination(result):
                            final_tool_result = result
                            termination_reason = "termination_tool"
                            break
                    if final_tool_result:
                        break

                if not step_result.tool_calls:
                    termination_reason = "no_tool_calls"
                    break

            final_message = (
                messages[-1] if messages else Message(role="assistant", content="")
            )

            return RunResult(
                final_message=final_message,
                history=messages,
                turn_count=turn_count,
                termination_reason=termination_reason,
                final_tool_result=final_tool_result,
                total_usage=total_usage if total_usage.total_tokens > 0 else None,
            )

        except Exception as exc:
            await self.observer.on_error(exc, f"turn {turn_count}")
            raise

        finally:
            total_duration_ms = int((time.monotonic() - start_time) * 1000)
            await self.observer.on_kernel_end(
                KernelEndEvent(
                    turn_count=turn_count,
                    termination_reason=termination_reason,
                    total_duration_ms=total_duration_ms,
                )
            )

    async def close(self) -> None:
        """Close the kernel and release resources."""
        await self._client.close()
