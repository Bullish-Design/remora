"""Shared agent execution pipeline.

This is THE ONE place where agent execution happens.  Both
``SwarmExecutor`` (CLI / headless) and ``AgentRunner`` (LSP) delegate
here so that bundle resolution, tool discovery, kernel wiring, and
audit-trail recording are identical regardless of entry point.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from structured_agents import Message, build_client

from remora.core.agents.kernel_factory import create_kernel, extract_response_text
from remora.core.agents.turn_context import (
    CairnDataProvider,
    CairnWorkspaceService,
    TurnContext,
    _build_prompt,
    build_turn_context,
    build_virtual_fs,
    discover_grail_tools,
    load_manifest,
)

if TYPE_CHECKING:
    from remora.core.config import Config
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of a single agent turn."""

    response_text: str
    kernel_events: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Observer that writes to EventStore + optional callback
# ---------------------------------------------------------------------------


class _CompositeObserver:
    """Observer that writes kernel events to EventStore and optionally
    forwards them to a caller-supplied callback (e.g. LSP UI events)."""

    def __init__(
        self,
        event_store: EventStore,
        swarm_id: str,
        on_kernel_event: Callable[[Any], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self.store = event_store
        self.swarm_id = swarm_id
        self.on_kernel_event = on_kernel_event
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)
        await self.store.append(self.swarm_id, event)
        if self.on_kernel_event:
            await self.on_kernel_event(event)


# ---------------------------------------------------------------------------
# Main execution function
# ---------------------------------------------------------------------------


async def execute_agent_turn(
    node,
    config: Config,
    event_store: EventStore,
    subscriptions: SubscriptionRegistry | None,
    swarm_id: str,
    project_root: Path,
    *,
    trigger_event: Any = None,
    workspace_service: CairnWorkspaceService | None = None,
    extra_tools: list[Any] | None = None,
    on_kernel_event: Callable[[Any], Coroutine[Any, Any, None]] | None = None,
    client: Any | None = None,
    chat_history: list[dict[str, str]] | None = None,
) -> ExecutionResult:
    """Run a single agent turn using the unified execution pipeline.

    This is THE ONE place where agent execution happens.  Both
    ``SwarmExecutor`` and ``AgentRunner`` delegate here.
    """
    logger.info("execute_agent_turn: starting for %s", node.node_id)

    turn_context: TurnContext | None = None
    try:
        turn_context = await build_turn_context(
            node=node,
            config=config,
            event_store=event_store,
            subscriptions=subscriptions,
            swarm_id=swarm_id,
            project_root=project_root,
            trigger_event=trigger_event,
            workspace_service=workspace_service,
            extra_tools=extra_tools,
            chat_history=chat_history,
            load_manifest_fn=load_manifest,
            workspace_service_cls=CairnWorkspaceService,
            data_provider_cls=CairnDataProvider,
            discover_grail_tools_fn=discover_grail_tools,
            build_virtual_fs_fn=build_virtual_fs,
            build_prompt_fn=_build_prompt,
        )

        # Create observer + kernel
        observer = _CompositeObserver(event_store, swarm_id, on_kernel_event)
        logger.info(
            "execute_agent_turn: model dispatch target base_url=%s model=%s timeout_s=%.1f",
            config.model_base_url,
            turn_context.model_name,
            config.timeout_s,
        )

        if client is None:
            client = build_client(
                {
                    "base_url": config.model_base_url,
                    "api_key": config.model_api_key or "EMPTY",
                    "model": turn_context.model_name,
                    "timeout": config.timeout_s,
                }
            )
            logger.info("execute_agent_turn: created model client")
        else:
            logger.info("execute_agent_turn: reusing caller-provided model client")

        kernel = create_kernel(
            model_name=turn_context.model_name,
            base_url=config.model_base_url,
            api_key=config.model_api_key or "EMPTY",
            timeout=config.timeout_s,
            tools=turn_context.tools,
            observer=observer,
            grammar_config=turn_context.manifest.grammar_config if turn_context.manifest.grammar_config else None,
            client=client,
        )

        # Run kernel
        try:
            messages: list[Message] = [
                Message(role="system", content=turn_context.manifest.system_prompt),
            ]
            for entry in turn_context.chat_history or []:
                role = entry.get("role")
                content = entry.get("content")
                if role and content:
                    messages.append(Message(role=cast(Any, role), content=content))
            messages.append(Message(role="user", content=turn_context.prompt))

            tool_schemas = [tool.schema for tool in turn_context.tools]
            if turn_context.manifest.grammar_config and not turn_context.manifest.grammar_config.send_tools_to_api:
                tool_schemas = []

            max_turns = getattr(turn_context.manifest, "max_turns", None) or config.max_turns
            logger.info(
                "execute_agent_turn: calling kernel.run with %d messages, %d tools, max_turns=%d",
                len(messages),
                len(tool_schemas),
                max_turns,
            )

            model_start = time.monotonic()
            try:
                result = await kernel.run(messages, tool_schemas, max_turns=max_turns)
            except Exception:
                logger.exception(
                    "execute_agent_turn: kernel.run failed base_url=%s model=%s",
                    config.model_base_url,
                    turn_context.model_name,
                )
                raise
            logger.info(
                "execute_agent_turn: kernel.run END duration_ms=%.1f",
                (time.monotonic() - model_start) * 1000,
            )
        finally:
            await kernel.close()

        # Extract response text
        response_text = extract_response_text(result)

        logger.info(
            "execute_agent_turn: completed for %s — %d chars response, %d kernel events",
            node.node_id,
            len(response_text),
            len(observer.events),
        )

        return ExecutionResult(
            response_text=response_text,
            kernel_events=observer.events,
        )
    finally:
        if turn_context and turn_context.created_workspace_service:
            close_start = time.monotonic()
            try:
                await turn_context.workspace_service.close()
            except Exception:
                logger.warning("execute_agent_turn: workspace service close failed", exc_info=True)
            else:
                logger.info(
                    "execute_agent_turn: workspace service closed duration_ms=%.1f",
                    (time.monotonic() - close_start) * 1000,
                )


__all__ = ["ExecutionResult", "execute_agent_turn"]
