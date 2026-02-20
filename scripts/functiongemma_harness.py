"""Minimal FunctionGemma harness wired to Remora tools."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import typer

from remora.config import RemoraConfig, RunnerConfig, load_config, resolve_grail_limits
from remora.discovery.models import CSTNode, NodeType
from remora.events import CompositeEventEmitter, EventEmitter, EventName, EventStatus, build_event_emitter
from remora.execution import ProcessIsolatedExecutor
from remora.llm_logger import LlmConversationLogger
from remora.orchestrator import RemoraAgentContext
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import SubagentDefinition, load_subagent_definition

app = typer.Typer(help="Hammer vLLM using a Remora harness agent.")


@dataclass
class CallResult:
    ok: bool
    tool_called: bool
    error: str | None


PROMPT_VARIANTS = [
    "Use simple_tool to echo payload ping.",
    "Call simple_tool with payload ping.",
    "Invoke simple_tool and echo payload ping.",
    "Run simple_tool to return the payload ping.",
]


class HarnessEventEmitter:
    enabled = True
    include_payloads = False
    max_payload_chars = 0

    def __init__(self) -> None:
        self.tool_called = False
        self.error: str | None = None

    def emit(self, payload: dict[str, object]) -> None:
        event = payload.get("event")
        if event == EventName.TOOL_CALL:
            self.tool_called = True
        if event == EventName.MODEL_RESPONSE and payload.get("status") == EventStatus.ERROR:
            self.error = str(payload.get("error"))
        if event == EventName.AGENT_ERROR:
            self.error = str(payload.get("error"))

    def close(self) -> None:
        return


def _wrap_event_emitter(base: EventEmitter, tracker: HarnessEventEmitter) -> CompositeEventEmitter:
    return CompositeEventEmitter(
        emitters=[base, tracker],
        enabled=True,
        include_payloads=True,
        max_payload_chars=base.max_payload_chars,
    )


def _build_tool_guide(tool_schemas: list[dict[str, Any]]) -> str:
    lines = ["Tools:"]
    for schema in tool_schemas:
        function = schema.get("function", {})
        name = function.get("name", "unknown")
        description = function.get("description", "").strip()
        parameters = function.get("parameters", {})
        required = parameters.get("required") or []
        required_list = ", ".join(required) if required else "none"
        if description:
            lines.append(f"- {name}: {description} (required: {required_list})")
        else:
            lines.append(f"- {name} (required: {required_list})")
    return "\n".join(lines)


def _build_node(prompt: str, index: int) -> CSTNode:
    node_id = uuid.uuid4().hex[:16]
    return CSTNode(
        node_id=node_id,
        node_type=NodeType.FUNCTION,
        name=f"harness_prompt_{index}",
        file_path=Path("harness_prompt.py"),
        start_byte=0,
        end_byte=len(prompt.encode("utf-8")),
        text=prompt,
        start_line=1,
        end_line=1,
    )


async def _run_once(
    definition: SubagentDefinition,
    config: RemoraConfig,
    runner_config: RunnerConfig,
    grail_dir: Path,
    grail_limits: dict[str, Any],
    prompt: str,
    index: int,
    executor: ProcessIsolatedExecutor,
    semaphore: asyncio.Semaphore,
    event_emitter: EventEmitter,
) -> CallResult:
    async with semaphore:
        node = _build_node(prompt, index)
        ctx = RemoraAgentContext(
            agent_id=f"harness-{uuid.uuid4().hex[:12]}",
            task="functiongemma_harness",
            operation=definition.name,
            node_id=node.node_id,
        )
        tracker = HarnessEventEmitter()
        composite_emitter = _wrap_event_emitter(event_emitter, tracker)
        runner = FunctionGemmaRunner(
            definition=definition,
            node=node,
            ctx=ctx,
            server_config=config.server,
            runner_config=runner_config,
            adapter_name=definition.model_id,
            event_emitter=composite_emitter,
            grail_executor=executor,
            grail_dir=grail_dir,
            grail_limits=grail_limits,
        )

        try:
            await runner.run()
            return CallResult(ok=True, tool_called=tracker.tool_called, error=tracker.error)
        except AgentError as exc:
            return CallResult(ok=False, tool_called=tracker.tool_called, error=str(exc))


async def _run_variant(
    definition: SubagentDefinition,
    config: RemoraConfig,
    runner_config: RunnerConfig,
    grail_dir: Path,
    grail_limits: dict[str, Any],
    prompt: str,
    concurrency: int,
    requests_per_variant: int,
    executor: ProcessIsolatedExecutor,
    event_emitter: EventEmitter,
) -> tuple[int, int, int]:
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        _run_once(
            definition,
            config,
            runner_config,
            grail_dir,
            grail_limits,
            prompt,
            index,
            executor,
            semaphore,
            event_emitter,
        )
        for index in range(requests_per_variant)
    ]
    results = await asyncio.gather(*tasks)
    ok_count = sum(1 for result in results if result.ok)
    tool_count = sum(1 for result in results if result.tool_called)
    error_count = len(results) - ok_count
    return ok_count, tool_count, error_count


async def _run_all(
    definition_path: Path,
    config_path: Path | None,
    tool_choice: str,
    max_tokens: int,
    concurrency: int,
    requests_per_variant: int,
    include_tool_guide: bool,
) -> None:
    config = load_config(config_path)
    definition = load_subagent_definition(definition_path, config.agents_dir)
    runner_config = config.runner.model_copy(
        update={
            "tool_choice": tool_choice,
            "max_tokens": max_tokens,
            "include_prompt_context": False,
            "include_tool_guide": include_tool_guide,
        }
    )
    grail_dir = Path(".grail")
    grail_dir.mkdir(parents=True, exist_ok=True)
    grail_limits = resolve_grail_limits(config.cairn)
    executor = ProcessIsolatedExecutor(max_workers=concurrency)
    event_emitter = build_event_emitter(config.event_stream)
    llm_logger: LlmConversationLogger | None = None
    if config.llm_log.enabled:
        output_path = config.llm_log.output or (
            (config.cairn.home or Path.home() / ".cache" / "remora") / "llm_conversations.log"
        )
        llm_logger = LlmConversationLogger(
            output=output_path,
            include_full_prompts=config.llm_log.include_full_prompts,
            max_content_lines=config.llm_log.max_content_lines,
        )
        llm_logger.open()
        emitters = cast(list[EventEmitter], [event_emitter, llm_logger])
        event_emitter = CompositeEventEmitter(
            emitters=emitters,
            enabled=True,
            include_payloads=True,
        )

    system_prompt = definition.initial_context.system_prompt
    if include_tool_guide:
        tool_guide = _build_tool_guide(definition.tool_schemas)
        if tool_guide:
            system_prompt = f"{system_prompt}\n{tool_guide}".strip()
    typer.echo("-")
    typer.echo("System prompt used:")
    typer.echo(system_prompt)
    typer.echo("-")

    start = time.monotonic()

    for prompt in PROMPT_VARIANTS:
        ok_count, tool_count, error_count = await _run_variant(
            definition,
            config,
            runner_config,
            grail_dir,
            grail_limits,
            prompt,
            concurrency,
            requests_per_variant,
            executor,
            event_emitter,
        )
        success_rate = (tool_count / requests_per_variant) * 100
        typer.echo("-")
        typer.echo(f"Prompt: {prompt}")
        typer.echo(f"Tool calls: {tool_count}/{requests_per_variant} ({success_rate:.1f}%)")
        typer.echo(f"OK responses: {ok_count} | Errors: {error_count}")

    elapsed = time.monotonic() - start
    typer.echo("-")
    typer.echo(f"Completed in {elapsed:.2f}s")
    await executor.shutdown()
    event_emitter.close()
    if llm_logger:
        llm_logger.close()



@app.command()
def main(
    definition_path: str = typer.Option(
        "harness/harness_subagent.yaml",
        help="Subagent definition path relative to agents_dir.",
    ),
    config_path: str | None = typer.Option(
        os.getenv("REMORA_CONFIG", None),
        help="Path to remora.yaml (defaults to repo root).",
    ),
    tool_choice: str = typer.Option(
        "auto",
        help="Tool choice mode: required or auto.",
    ),
    max_tokens: int = typer.Option(256, help="Max tokens for model responses."),
    concurrency: int = typer.Option(25, help="Max concurrent requests."),
    requests_per_variant: int = typer.Option(40, help="Requests per prompt."),
    include_tool_guide: bool = typer.Option(
        True, help="Include a compact tool guide in the system prompt."
    ),
) -> None:
    """Run a high-concurrency FunctionGemma tool-call sweep via Remora."""
    asyncio.run(
        _run_all(
            Path(definition_path),
            Path(config_path) if config_path else None,
            tool_choice,
            max_tokens,
            concurrency,
            requests_per_variant,
            include_tool_guide,
        )
    )


if __name__ == "__main__":
    app()
