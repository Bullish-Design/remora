"""Swarm executor for reactive agent execution.

This module provides SwarmExecutor which runs single agent turns
in response to events from the EventStore trigger queue.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from structured_agents.agent import get_response_parser, load_manifest
from structured_agents.client import build_client
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.types import Message

from remora.core.agent_state import AgentState
from remora.core.discovery import CSTNode
from remora.core.event_store import EventStore
from remora.core.events import AgentMessageEvent
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.core.workspace import CairnDataProvider
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.utils import PathLike, PathResolver, truncate

if TYPE_CHECKING:
    from remora.core.config import Config
    from remora.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class SwarmExecutor:
    """Executor for single agent turns in reactive swarm mode."""

    def __init__(
        self,
        config: "Config",
        event_bus: "EventBus | None",
        event_store: EventStore,
        subscriptions: SubscriptionRegistry,
        swarm_state: SwarmState,
        swarm_id: str,
        project_root: Path,
    ):
        self.config = config
        self._event_bus = event_bus
        self._event_store = event_store
        self._subscriptions = subscriptions
        self._swarm_state = swarm_state
        self._swarm_id = swarm_id
        self._project_root = project_root
        self._path_resolver = PathResolver(project_root)

        self._workspace_service = CairnWorkspaceService(
            config=config,
            swarm_root=config.swarm_root,
            project_root=project_root,
        )
        self._workspace_initialized = False

    async def run_agent(self, state: AgentState, trigger_event: Any = None) -> str:
        """Run a single agent turn.

        Args:
            state: The agent state to run
            trigger_event: The event that triggered this agent (optional)

        Returns:
            The agent's response as a string
        """
        bundle_path = self._resolve_bundle_path(state)
        manifest = load_manifest(bundle_path)

        if not self._workspace_initialized:
            await self._workspace_service.initialize()
            self._workspace_initialized = True
            
        workspace = await self._workspace_service.get_agent_workspace(state.agent_id)
        externals = self._workspace_service.get_externals(state.agent_id, workspace)

        externals["agent_id"] = state.agent_id
        externals["correlation_id"] = getattr(trigger_event, "correlation_id", None) if trigger_event else None

        async def _emit_event(event_type: str, event_obj: Any) -> None:
            await self._event_store.append(self._swarm_id, event_obj)

        async def _register_sub(agent_id: str, pattern: Any) -> None:
            await self._subscriptions.register(agent_id, pattern)

        async def _unsubscribe_subscription(subscription_id: int) -> str:
            """Remove a subscription by ID."""
            removed = await self._subscriptions.unregister(subscription_id)
            if removed:
                return f"Subscription {subscription_id} removed."
            return f"No subscription found for {subscription_id}."

        async def _broadcast(to_pattern: str, content: str) -> str:
            """Broadcast a message to multiple agents."""
            if not emit_event:
                return "Error: Swarm event emitter is not configured."
            metadata = await self._swarm_state.get_agent(state.agent_id)
            if metadata is None:
                return "Error: Agent metadata is unavailable."

            agents = await self._swarm_state.list_agents()
            pattern = to_pattern.lower()

            if pattern == "children":
                targets = [agent.agent_id for agent in agents if agent.parent_id == state.agent_id]
            elif pattern == "siblings":
                if not metadata.parent_id:
                    return "Error: No parent metadata available for sibling broadcast."
                targets = [
                    agent.agent_id
                    for agent in agents
                    if agent.parent_id == metadata.parent_id and agent.agent_id != state.agent_id
                ]
            elif pattern.startswith("file:"):
                file_path = to_pattern[5:].strip()
                targets = [
                    agent.agent_id
                    for agent in agents
                    if agent.file_path == file_path or agent.file_path.endswith(file_path)
                ]
            else:
                return f"Unknown broadcast pattern: {to_pattern}"

            if not targets:
                return "No agents matched the broadcast pattern."

            for target in targets:
                event = AgentMessageEvent(
                    from_agent=state.agent_id,
                    to_agent=target,
                    content=content,
                    correlation_id=externals.get("correlation_id"),
                )
                await emit_event("AgentMessageEvent", event)

            return f"Broadcast sent to {len(targets)} agents via {to_pattern}."

        async def _query_agents(filter_type: str | None = None) -> list[AgentMetadata]:
            """Query agent metadata filtered by node type."""
            agents = await self._swarm_state.list_agents()
            if not filter_type:
                return agents
            target_type = filter_type.lower()
            return [agent for agent in agents if agent.node_type.lower() == target_type]

        externals["emit_event"] = _emit_event
        externals["register_subscription"] = _register_sub
        externals["unsubscribe_subscription"] = _unsubscribe_subscription
        externals["broadcast"] = _broadcast
        externals["query_agents"] = _query_agents

        data_provider = CairnDataProvider(workspace, self._path_resolver)
        node = _state_to_cst_node(state)
        files = await data_provider.load_files(node)

        prompt = self._build_prompt(
            state,
            node,
            files,
            trigger_event=trigger_event,
            requires_context=getattr(manifest, "requires_context", True),
        )

        async def files_provider() -> dict[str, str | bytes]:
            current_files = await data_provider.load_files(node)
            return dict(build_virtual_fs(current_files))

        tools = discover_grail_tools(
            manifest.agents_dir,
            externals=externals,
            files_provider=files_provider,
        )

        model_name = self._resolve_model_name(bundle_path, manifest)
        result = await self._run_kernel(state, manifest, prompt, tools, model_name=model_name)

        response_text = str(result)
        truncated_response = truncate(response_text, max_len=self.config.truncation_limit)

        state.chat_history.append({"role": "user", "content": prompt})
        state.chat_history.append({"role": "assistant", "content": truncated_response})
        state.chat_history = state.chat_history[-10:]

        try:
            if (self._project_root / ".jj").exists():
                message = f"Agent {state.agent_id} completed turn."
                process = await asyncio.create_subprocess_exec(
                    "jj",
                    "commit",
                    "-m",
                    message,
                    cwd=str(self._project_root),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await process.wait()
        except Exception as exc:  # pragma: no cover - best effort commit
            logger.warning("Failed to create JJ commit: %s", exc)

        return truncated_response

    def _resolve_bundle_path(self, state: AgentState) -> Path:
        bundle_root = Path(self.config.bundle_root)
        mapping = self.config.bundle_mapping
        if state.node_type not in mapping:
            logger.warning(f"No bundle mapping for node_type: {state.node_type}, using default")
            return bundle_root
        return bundle_root / mapping[state.node_type]

    def _resolve_model_name(self, bundle_path: Path, manifest: Any) -> str:
        path = bundle_path / "bundle.yaml" if bundle_path.is_dir() else bundle_path
        override = None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            model_data = data.get("model")
            if isinstance(model_data, dict):
                override = model_data.get("id") or model_data.get("name") or model_data.get("model")
        except Exception:
            override = None
        if override:
            return str(override)
        return self.config.model_default or getattr(manifest, "model", "")

    async def _run_kernel(
        self,
        state: AgentState,
        manifest: Any,
        prompt: str,
        tools: list[Any],
        *,
        model_name: str,
    ) -> Any:
        parser = get_response_parser(manifest.model)
        pipeline = ConstraintPipeline(manifest.grammar_config) if manifest.grammar_config else None
        adapter = ModelAdapter(name=manifest.model, response_parser=parser, constraint_pipeline=pipeline)
        client = build_client(
            {
                "base_url": self.config.model_base_url,
                "api_key": self.config.model_api_key or "EMPTY",
                "model": model_name,
                "timeout": self.config.timeout_s,
            }
        )
        class _EventStoreObserver:
            def __init__(self, store: EventStore, swarm_id: str):
                self.store = store
                self.swarm_id = swarm_id
            
            async def emit(self, event: Any) -> None:
                await self.store.append(self.swarm_id, event)
                
        observer = _EventStoreObserver(self._event_store, self._swarm_id)
        kernel = AgentKernel(client=client, adapter=adapter, tools=tools, observer=observer)
        try:
            messages: list[Message] = [
                Message(role="system", content=manifest.system_prompt),
            ]
            for entry in getattr(state, "chat_history", []):
                role = entry.get("role")
                content = entry.get("content")
                if role and content:
                    messages.append(Message(role=role, content=content))
            messages.append(Message(role="user", content=prompt))
            tool_schemas = [tool.schema for tool in tools]
            if manifest.grammar_config and not manifest.grammar_config.send_tools_to_api:
                tool_schemas = []
            max_turns = getattr(manifest, "max_turns", None) or self.config.max_turns
            return await kernel.run(messages, tool_schemas, max_turns=max_turns)
        finally:
            await kernel.close()

    def _build_prompt(
        self,
        state: AgentState,
        node: CSTNode,
        files: dict[str, Any],
        *,
        trigger_event: Any = None,
        requires_context: bool = True,
    ) -> str:
        sections: list[str] = []
        sections.append(f"# Target: {state.full_name or state.agent_id}")
        sections.append(f"File: {state.file_path}")
        if state.range:
            sections.append(f"Lines: {state.range[0]}-{state.range[1]}")
        code = files.get(self._path_resolver.to_workspace_path(state.file_path)) or files.get(state.file_path)
        if code is not None:
            sections.append("")
            sections.append("## Code")
            sections.append("```")
            sections.append(code.decode() if isinstance(code, bytes) else code)
            sections.append("```")
        if trigger_event is not None:
            sections.append("")
            sections.append("## Trigger Event")
            sections.append(f"Type: {type(trigger_event).__name__}")
            event_content = getattr(trigger_event, "content", str(trigger_event))
            if event_content:
                sections.append(f"Content: {event_content}")
        if requires_context:
            history_items = []
            for entry in state.chat_history[-5:]:
                role = entry.get("role")
                content = entry.get("content")
                if role and content:
                    history_items.append(f"{role.capitalize()}: {content}")
            if history_items:
                sections.append("")
                sections.append("## Recent Chat History")
                sections.extend(history_items)
        return "\n".join(sections)


def _state_to_cst_node(state: AgentState) -> CSTNode:
    start_line = state.range[0] if state.range else 1
    end_line = state.range[1] if state.range else 1
    return CSTNode(
        node_id=state.agent_id,
        node_type=state.node_type,
        name=state.name or "",
        full_name=state.full_name or "",
        file_path=state.file_path,
        text="",
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=0,
    )


__all__ = ["SwarmExecutor"]
