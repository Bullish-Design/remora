"""Swarm executor for reactive agent execution.

This module provides SwarmExecutor which runs single agent turns
in response to events from the EventStore trigger queue.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml
from structured_agents.agent import load_manifest
from structured_agents.client import build_client
from structured_agents.types import Message

from remora.core.kernel_factory import create_kernel

from remora.core.agent_node import AgentNode
from remora.core.agent_context import AgentContext
from remora.core.discovery import CSTNode
from remora.core.event_store import EventStore
from remora.core.events import AgentMessageEvent
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.core.workspace import CairnDataProvider
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.utils import PathLike, PathResolver, truncate

if TYPE_CHECKING:
    from remora.core.config import Config
    from remora.core.event_bus import EventBus

logger = logging.getLogger(__name__)


def _agent_node_to_cst_node(node: AgentNode) -> CSTNode:
    """Convert an AgentNode to a CSTNode for data_provider compatibility."""
    return CSTNode(
        node_id=node.node_id,
        node_type=node.node_type,
        name=node.name,
        full_name=node.full_name,
        file_path=node.file_path,
        text=node.source_code,
        start_line=node.start_line,
        end_line=node.end_line,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
    )


class SwarmExecutor:
    """Executor for single agent turns in reactive swarm mode."""

    def __init__(
        self,
        config: "Config",
        event_bus: "EventBus | None",
        event_store: EventStore,
        subscriptions: SubscriptionRegistry,
        swarm_id: str,
        project_root: Path,
    ):
        self.config = config
        self._event_bus = event_bus
        self._event_store = event_store
        self._subscriptions = subscriptions
        self._swarm_id = swarm_id
        self._project_root = project_root
        self._path_resolver = PathResolver(project_root)

        self._workspace_service = CairnWorkspaceService(
            config=config,
            swarm_root=config.swarm_root,
            project_root=project_root,
        )
        self._workspace_initialized = False

        # Connection pooling: create the LLM client once and reuse it
        self._client = build_client(
            {
                "base_url": config.model_base_url,
                "api_key": config.model_api_key or "EMPTY",
                "model": config.model_default,
                "timeout": config.timeout_s,
            }
        )

    async def run_agent(self, node: AgentNode, trigger_event: Any = None) -> str:
        """Run a single agent turn.

        Args:
            node: The AgentNode to run
            trigger_event: The event that triggered this agent (optional)

        Returns:
            The agent's response as a string
        """
        logger.info(f"SwarmExecutor.run_agent starting for {node.node_id}")

        bundle_path = self._resolve_bundle_path(node)
        logger.info(f"Resolved bundle path: {bundle_path}")

        manifest = load_manifest(bundle_path)
        logger.info(f"Loaded manifest: {manifest.name if hasattr(manifest, 'name') else 'unknown'}")

        if not self._workspace_initialized:
            logger.info("Initializing workspace service...")
            await self._workspace_service.initialize()
            self._workspace_initialized = True
            logger.info("Workspace service initialized")

        logger.info(f"Getting workspace for agent {node.node_id}")
        workspace = await self._workspace_service.get_agent_workspace(node.node_id)
        cairn_externals = self._workspace_service.get_externals(node.node_id, workspace)
        logger.info("Workspace and externals ready")

        correlation_id = getattr(trigger_event, "correlation_id", None) if trigger_event else None

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
            if not _emit_event:
                return "Error: Swarm event emitter is not configured."
            current_node = await self._event_store.get_node(node.node_id)
            if current_node is None:
                return "Error: Agent metadata is unavailable."

            agents = await self._event_store.list_nodes()
            pattern = to_pattern.lower()

            if pattern == "children":
                targets = [a.node_id for a in agents if a.parent_id == node.node_id]
            elif pattern == "siblings":
                if not current_node.parent_id:
                    return "Error: No parent metadata available for sibling broadcast."
                targets = [
                    a.node_id for a in agents if a.parent_id == current_node.parent_id and a.node_id != node.node_id
                ]
            elif pattern.startswith("file:"):
                file_path = to_pattern[5:].strip()
                targets = [a.node_id for a in agents if a.file_path == file_path or a.file_path.endswith(file_path)]
            else:
                return f"Unknown broadcast pattern: {to_pattern}"

            if not targets:
                return "No agents matched the broadcast pattern."

            for target in targets:
                event = AgentMessageEvent(
                    from_agent=node.node_id,
                    to_agent=target,
                    content=content,
                    correlation_id=correlation_id,
                )
                await _emit_event("AgentMessageEvent", event)

            return f"Broadcast sent to {len(targets)} agents via {to_pattern}."

        async def _query_agents(filter_type: str | None = None) -> list[AgentNode]:
            """Query agent metadata filtered by node type."""
            agents = await self._event_store.list_nodes()
            if not filter_type:
                return agents
            target_type = filter_type.lower()
            return [agent for agent in agents if agent.node_type.lower() == target_type]

        agent_context = AgentContext(
            agent_id=node.node_id,
            correlation_id=correlation_id,
            emit_event=_emit_event,
            register_subscription=_register_sub,
            unsubscribe_subscription=_unsubscribe_subscription,
            broadcast=_broadcast,
            query_agents=_query_agents,
            cairn_externals=cairn_externals,
        )

        data_provider = CairnDataProvider(workspace, self._path_resolver)
        cst_node = _agent_node_to_cst_node(node)
        files = await data_provider.load_files(cst_node)

        # Get chat history from EventStore recent events
        recent_events = await self._event_store.get_recent_events(node.node_id, limit=self.config.chat_history_limit)
        chat_history: list[dict[str, str]] = []
        for ev in reversed(recent_events):  # reversed because get_recent_events returns newest-first
            payload = ev.get("payload", {})
            if ev.get("event_type") == "AgentMessageEvent":
                if ev.get("to_agent") == node.node_id:
                    chat_history.append({"role": "user", "content": payload.get("content", "")})
                elif ev.get("from_agent") == node.node_id:
                    chat_history.append({"role": "assistant", "content": payload.get("content", "")})

        prompt = self._build_prompt(
            node,
            cst_node,
            files,
            chat_history=chat_history,
            trigger_event=trigger_event,
            requires_context=getattr(manifest, "requires_context", True),
        )

        async def files_provider() -> dict[str, str | bytes]:
            current_files = await data_provider.load_files(cst_node)
            fs: dict[str, str | bytes] = dict(build_virtual_fs(current_files))
            return fs

        # Only discover tools if agents_dir is set (chat bundles have no tools)
        tools = []
        if manifest.agents_dir:
            tools = discover_grail_tools(
                manifest.agents_dir,
                context=agent_context,
                files_provider=files_provider,
            )
        logger.info(f"Discovered {len(tools)} tools (agents_dir={manifest.agents_dir})")

        model_name = self._resolve_model_name(bundle_path, manifest)
        logger.info(f"Using model: {model_name} at {self.config.model_base_url}")
        logger.info(f"Running kernel with {len(tools)} tools, prompt length={len(prompt)}")

        result = await self._run_kernel(manifest, prompt, tools, chat_history=chat_history, model_name=model_name)
        logger.info(f"Kernel completed with result type: {type(result)}")

        # Extract actual content from RunResult
        response_text = ""
        if hasattr(result, "final_message") and result.final_message:
            msg = result.final_message
            logger.info(f"final_message type: {type(msg)}, has content: {hasattr(msg, 'content')}")
            if hasattr(msg, "content") and msg.content:
                response_text = msg.content
                logger.info(f"Extracted content from final_message.content")
            else:
                response_text = str(result)
                logger.info(f"Using str(result) fallback - content was empty")
        elif hasattr(result, "content") and result.content:
            response_text = result.content
            logger.info(f"Extracted content from result.content")
        else:
            response_text = str(result)
            logger.info(f"Using str(result) fallback")

        logger.info(f"Response text (first 100 chars): {response_text[:100] if response_text else 'empty'}")
        truncated_response = truncate(response_text, max_len=self.config.truncation_limit)

        return truncated_response

    def _resolve_bundle_path(self, node: AgentNode) -> Path:
        bundle_root = Path(self.config.bundle_root)
        mapping = self.config.bundle_mapping
        if node.node_type not in mapping:
            logger.warning(f"No bundle mapping for node_type: {node.node_type}, using default")
            return bundle_root
        return bundle_root / mapping[node.node_type]

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
        manifest: Any,
        prompt: str,
        tools: list[Any],
        *,
        chat_history: list[dict[str, str]] | None = None,
        model_name: str,
    ) -> Any:
        class _EventStoreObserver:
            def __init__(self, store: EventStore, swarm_id: str):
                self.store = store
                self.swarm_id = swarm_id

            async def emit(self, event: Any) -> None:
                await self.store.append(self.swarm_id, event)

        observer = _EventStoreObserver(self._event_store, self._swarm_id)
        kernel = create_kernel(
            model_name=model_name,
            base_url=self.config.model_base_url,
            api_key=self.config.model_api_key or "EMPTY",
            timeout=self.config.timeout_s,
            tools=tools,
            observer=observer,
            grammar_config=manifest.grammar_config if manifest.grammar_config else None,
            client=self._client,
        )
        logger.info(f"Created kernel with client pointing to {self.config.model_base_url}")

        try:
            messages: list[Message] = [
                Message(role="system", content=manifest.system_prompt),
            ]
            logger.info(f"Prepared {len(messages)} initial messages")
            for entry in chat_history or []:
                role = entry.get("role")
                content = entry.get("content")
                if role and content:
                    messages.append(Message(role=cast(Any, role), content=content))
            messages.append(Message(role="user", content=prompt))
            tool_schemas = [tool.schema for tool in tools]
            if manifest.grammar_config and not manifest.grammar_config.send_tools_to_api:
                tool_schemas = []
            max_turns = getattr(manifest, "max_turns", None) or self.config.max_turns
            logger.info(
                f"Calling kernel.run with {len(messages)} messages, {len(tool_schemas)} tools, max_turns={max_turns}"
            )
            result = await kernel.run(messages, tool_schemas, max_turns=max_turns)
            logger.info("kernel.run completed successfully")
            return result
        finally:
            await kernel.close()

    def _build_prompt(
        self,
        node: AgentNode,
        cst_node: CSTNode,
        files: dict[str, Any],
        *,
        chat_history: list[dict[str, str]] | None = None,
        trigger_event: Any = None,
        requires_context: bool = True,
        scaffold_context: dict[str, Any] | None = None,
    ) -> str:
        sections: list[str] = []
        sections.append(f"# Target: {node.full_name or node.node_id}")
        sections.append(f"File: {node.file_path}")
        if node.start_line and node.end_line:
            sections.append(f"Lines: {node.start_line}-{node.end_line}")
        code = files.get(self._path_resolver.to_workspace_path(node.file_path)) or files.get(node.file_path)
        if code is not None:
            lang = _lang_tag_for(node.file_path)
            sections.append("")
            sections.append("## Code")
            sections.append(f"```{lang}")
            sections.append(code.decode() if isinstance(code, bytes) else code)
            sections.append("```")
        if trigger_event is not None:
            sections.append("")
            sections.append("## Trigger Event")
            sections.append(f"Type: {type(trigger_event).__name__}")
            event_content = getattr(trigger_event, "content", str(trigger_event))
            if event_content:
                sections.append(f"Content: {event_content}")
        if requires_context and chat_history:
            history_items = []
            for entry in chat_history[-self.config.chat_history_limit :]:
                role = entry.get("role")
                content = entry.get("content")
                if role and content:
                    history_items.append(f"{role.capitalize()}: {content}")
            if history_items:
                sections.append("")
                sections.append("## Recent Chat History")
                sections.extend(history_items)
        # Scaffold context enrichment: when a scaffold node has context,
        # add parent source, sibling info, and intent to the prompt.
        if node.status == "scaffold" and scaffold_context:
            subsections: list[str] = []
            parent_source = scaffold_context.get("parent_source", "")
            siblings = scaffold_context.get("siblings", [])
            intent = scaffold_context.get("intent", "")

            if parent_source:
                lang = _lang_tag_for(node.file_path)
                subsections.append("### Parent Source")
                subsections.append(f"```{lang}")
                subsections.append(parent_source)
                subsections.append("```")

            if siblings:
                subsections.append("### Siblings")
                for sib in siblings:
                    subsections.append(f"- {sib['name']} ({sib['node_type']})")

            if intent:
                subsections.append("### Intent")
                subsections.append(intent)

            if subsections:
                sections.append("")
                sections.append("## Scaffold Context")
                sections.extend(subsections)
        return "\n".join(sections)


_LANG_TAGS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sh": "bash",
    ".rs": "rust",
    ".go": "go",
}


def _lang_tag_for(file_path: str) -> str:
    """Return a markdown language tag for a file path, or empty string if unknown."""
    suffix = Path(file_path).suffix.lower()
    return _LANG_TAGS.get(suffix, "")


__all__ = ["SwarmExecutor"]
