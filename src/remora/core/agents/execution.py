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

from remora.core.agents.agent_context import AgentContext
from remora.core.agents.agent_node import AgentNode
from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
from remora.core.code.discovery import CSTNode
from remora.core.store.event_store import EventStore
from remora.core.events.events import AgentMessageEvent, ScaffoldRequestEvent
from remora.core.agents.kernel_factory import create_kernel
from remora.core.manifest import load_manifest
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.core.agents.workspace import AgentWorkspace, CairnDataProvider
from remora.utils import PathResolver
from remora.utils.languages import EXTENSION_TO_LANGUAGE as _LANG_TAGS

if TYPE_CHECKING:
    from remora.core.config import Config

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
# Helpers (extracted from SwarmExecutor)
# ---------------------------------------------------------------------------

def _lang_tag_for(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    return _LANG_TAGS.get(suffix, "")


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


def _resolve_bundle_path(node: AgentNode, config: Config) -> Path:
    """Resolve the bundle directory for a node based on ``bundle_mapping``."""
    bundle_root = Path(config.bundle_root)
    mapping = config.bundle_mapping
    if node.node_type not in mapping:
        logger.warning("No bundle mapping for node_type: %s, using default", node.node_type)
        return bundle_root
    return bundle_root / mapping[node.node_type]


def _resolve_model_name(bundle_path: Path, manifest: Any, config: Config) -> str:
    """Resolve the model name from bundle YAML, manifest, or config default."""
    import yaml

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
    return config.model_default or getattr(manifest, "model", "")


def _build_prompt(
    node: AgentNode,
    cst_node: CSTNode,
    files: dict[str, Any],
    path_resolver: PathResolver,
    config: Config,
    *,
    chat_history: list[dict[str, str]] | None = None,
    trigger_event: Any = None,
    requires_context: bool = True,
    scaffold_context: dict[str, Any] | None = None,
) -> str:
    """Build the user prompt for an agent turn."""
    sections: list[str] = []
    sections.append(f"# Target: {node.full_name or node.node_id}")
    sections.append(f"File: {node.file_path}")
    if node.start_line and node.end_line:
        sections.append(f"Lines: {node.start_line}-{node.end_line}")

    code = files.get(path_resolver.to_workspace_path(node.file_path)) or files.get(node.file_path)
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
        for entry in chat_history[-config.chat_history_limit :]:
            role = entry.get("role")
            content = entry.get("content")
            if role and content:
                history_items.append(f"{role.capitalize()}: {content}")
        if history_items:
            sections.append("")
            sections.append("## Recent Chat History")
            sections.extend(history_items)

    # Scaffold context enrichment for scaffold-status nodes
    if scaffold_context is not None:
        parent_source = scaffold_context.get("parent_source", "")
        siblings = scaffold_context.get("siblings", [])
        intent = scaffold_context.get("intent", "")

        # Only add the section if at least one sub-section has content
        if parent_source or siblings or intent:
            sections.append("")
            sections.append("## Scaffold Context")
            if parent_source:
                sections.append("")
                sections.append("### Parent Source")
                sections.append(f"```\n{parent_source}\n```")
            if siblings:
                sections.append("")
                sections.append("### Siblings")
                for sib in siblings:
                    sections.append(f"- {sib['name']} ({sib['node_type']})")
            if intent:
                sections.append("")
                sections.append("### Intent")
                sections.append(intent)

    return "\n".join(sections)


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
    node: AgentNode,
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

    Parameters
    ----------
    node:
        The ``AgentNode`` to execute.
    config:
        Remora configuration.
    event_store:
        Event store for reading/writing events.
    subscriptions:
        Subscription registry for event matching.
    swarm_id:
        Identifier for the swarm stream in EventStore.
    project_root:
        Root directory of the project.
    trigger_event:
        The event that triggered this agent turn (optional).
    workspace_service:
        Pre-initialized workspace service.  If ``None``, a new one
        is created and initialized.
    extra_tools:
        Additional tools to provide to the kernel (e.g. LSP-specific
        tools like ``rewrite_self``, ``message_node``, ``read_node``).
    on_kernel_event:
        Optional async callback invoked for every kernel event.  Used
        by the LSP path to forward events to the editor UI.
    client:
        Pre-built LLM client for connection pooling.  If ``None``, a
        new one is created.
    chat_history:
        Pre-built chat history.  If ``None``, it is loaded from
        ``EventStore.get_recent_events()``.
    """
    logger.info("execute_agent_turn: starting for %s", node.node_id)

    # 1. Resolve bundle + manifest
    bundle_path = _resolve_bundle_path(node, config)
    manifest = load_manifest(bundle_path)
    logger.info("execute_agent_turn: bundle=%s manifest=%s", bundle_path, getattr(manifest, "name", "?"))

    created_workspace_service = False
    workspace: AgentWorkspace

    # 2. Workspace setup
    logger.info("execute_agent_turn: initializing workspace service")
    if workspace_service is None:
        created_workspace_service = True
        workspace_service = CairnWorkspaceService(
            config=config,
            swarm_root=config.swarm_root,
            project_root=project_root,
        )

        init_start = time.monotonic()
        # Keep per-turn workspace initialization lightweight. File contents are
        # synced on demand via ensure_file_synced() when accessed.
        await workspace_service.initialize(sync_mode=SyncMode.NONE)
        logger.info(
            "execute_agent_turn: workspace service initialized mode=none duration_ms=%.1f",
            (time.monotonic() - init_start) * 1000,
        )

    logger.info("execute_agent_turn: getting agent workspace")
    ws_start = time.monotonic()
    workspace = await workspace_service.get_agent_workspace(node.node_id)
    logger.info(
        "execute_agent_turn: get_agent_workspace END duration_ms=%.1f agent=%s",
        (time.monotonic() - ws_start) * 1000,
        node.node_id,
    )
    cairn_externals = workspace_service.get_externals(node.node_id, workspace)

    # 3. Build AgentContext for swarm tools
    logger.info("execute_agent_turn: building AgentContext")
    correlation_id = getattr(trigger_event, "correlation_id", None) if trigger_event else None
    path_resolver = PathResolver(project_root)

    async def _emit_event(event_type: str, event_obj: Any) -> None:
        await event_store.append(swarm_id, event_obj)

    async def _register_sub(agent_id: str, pattern: Any) -> None:
        if subscriptions is not None:
            await subscriptions.register(agent_id, pattern)

    async def _unsubscribe_subscription(subscription_id: int) -> str:
        if subscriptions is None:
            return "Subscriptions not available."
        removed = await subscriptions.unregister(subscription_id)
        if removed:
            return f"Subscription {subscription_id} removed."
        return f"No subscription found for {subscription_id}."

    async def _broadcast(to_pattern: str, content: str) -> str:
        current_node = await event_store.nodes.get_node(node.node_id)
        if current_node is None:
            return "Error: Agent metadata is unavailable."
        agents = await event_store.nodes.list_nodes()
        pattern = to_pattern.lower()
        if pattern == "children":
            targets = [a.node_id for a in agents if a.parent_id == node.node_id]
        elif pattern == "siblings":
            if not current_node.parent_id:
                return "Error: No parent metadata available for sibling broadcast."
            targets = [a.node_id for a in agents if a.parent_id == current_node.parent_id and a.node_id != node.node_id]
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
        agents = await event_store.nodes.list_nodes()
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

    try:
        # 4. Load workspace files + build prompt
        logger.info("execute_agent_turn: loading workspace files")
        data_provider = CairnDataProvider(workspace, path_resolver)
        cst_node = _agent_node_to_cst_node(node)
        files = await data_provider.load_files(cst_node)

        logger.info("execute_agent_turn: loading chat history")
        if chat_history is None:
            recent_events = await event_store.get_recent_events(node.node_id, limit=config.chat_history_limit)
            chat_history = []
            for ev in reversed(recent_events):
                payload = ev.get("payload", {})
                if ev.get("event_type") == "AgentMessageEvent":
                    if ev.get("to_agent") == node.node_id:
                        chat_history.append({"role": "user", "content": payload.get("content", "")})
                    elif ev.get("from_agent") == node.node_id:
                        chat_history.append({"role": "assistant", "content": payload.get("content", "")})

        # 4a. Build scaffold context if trigger is ScaffoldRequestEvent
        scaffold_context: dict[str, Any] | None = None
        if isinstance(trigger_event, ScaffoldRequestEvent):
            scaffold_context = {"parent_source": "", "siblings": [], "intent": getattr(trigger_event, "intent", "")}
            if trigger_event.parent_id:
                parent_node = await event_store.nodes.get_node(trigger_event.parent_id)
                if parent_node is not None:
                    scaffold_context["parent_source"] = parent_node.source_code or ""
            # Siblings: nodes with same parent_id, excluding self
            all_nodes = await event_store.nodes.list_nodes()
            scaffold_context["siblings"] = [
                {"name": n.name, "node_type": n.node_type}
                for n in all_nodes
                if n.parent_id == trigger_event.parent_id and n.node_id != node.node_id
            ]

        logger.info("execute_agent_turn: building prompt")
        prompt = _build_prompt(
            node,
            cst_node,
            files,
            path_resolver,
            config,
            chat_history=chat_history,
            trigger_event=trigger_event,
            requires_context=getattr(manifest, "requires_context", True),
            scaffold_context=scaffold_context,
        )

        # 5. Discover tools (Grail + swarm + extra_tools)
        logger.info("execute_agent_turn: discovering tools")

        async def files_provider() -> dict[str, str | bytes]:
            current_files = await data_provider.load_files(cst_node)
            fs: dict[str, str | bytes] = dict(build_virtual_fs(current_files))
            return fs

        tools: list[Any] = []
        if manifest.agents_dir:
            tools = discover_grail_tools(
                manifest.agents_dir,
                context=agent_context,
                files_provider=files_provider,
            )

        # Add any extra tools (e.g. LSP-specific tools)
        if extra_tools:
            tools.extend(extra_tools)

        logger.info("execute_agent_turn: %d tools discovered", len(tools))

        # 6. Create observer + kernel
        model_name = _resolve_model_name(bundle_path, manifest, config)
        observer = _CompositeObserver(event_store, swarm_id, on_kernel_event)
        logger.info(
            "execute_agent_turn: model dispatch target base_url=%s model=%s timeout_s=%.1f",
            config.model_base_url,
            model_name,
            config.timeout_s,
        )

        if client is None:
            client = build_client(
                {
                    "base_url": config.model_base_url,
                    "api_key": config.model_api_key or "EMPTY",
                    "model": model_name,
                    "timeout": config.timeout_s,
                }
            )
            logger.info("execute_agent_turn: created model client")
        else:
            logger.info("execute_agent_turn: reusing caller-provided model client")

        kernel = create_kernel(
            model_name=model_name,
            base_url=config.model_base_url,
            api_key=config.model_api_key or "EMPTY",
            timeout=config.timeout_s,
            tools=tools,
            observer=observer,
            grammar_config=manifest.grammar_config if manifest.grammar_config else None,
            client=client,
        )

        # 7. Run kernel
        try:
            messages: list[Message] = [
                Message(role="system", content=manifest.system_prompt),
            ]
            for entry in chat_history or []:
                role = entry.get("role")
                content = entry.get("content")
                if role and content:
                    messages.append(Message(role=cast(Any, role), content=content))
            messages.append(Message(role="user", content=prompt))

            tool_schemas = [tool.schema for tool in tools]
            if manifest.grammar_config and not manifest.grammar_config.send_tools_to_api:
                tool_schemas = []

            max_turns = getattr(manifest, "max_turns", None) or config.max_turns
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
                    model_name,
                )
                raise
            logger.info(
                "execute_agent_turn: kernel.run END duration_ms=%.1f",
                (time.monotonic() - model_start) * 1000,
            )
        finally:
            await kernel.close()

        # 8. Extract response text
        response_text = ""
        if hasattr(result, "final_message") and result.final_message:
            msg = result.final_message
            if hasattr(msg, "content") and msg.content:
                response_text = msg.content
            else:
                response_text = str(result)
        elif hasattr(result, "content") and result.content:
            response_text = result.content
        else:
            response_text = str(result)

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
        if created_workspace_service and workspace_service is not None:
            close_start = time.monotonic()
            try:
                await workspace_service.close()
            except Exception:
                logger.warning("execute_agent_turn: workspace service close failed", exc_info=True)
            else:
                logger.info(
                    "execute_agent_turn: workspace service closed duration_ms=%.1f",
                    (time.monotonic() - close_start) * 1000,
                )


__all__ = ["ExecutionResult", "execute_agent_turn"]
