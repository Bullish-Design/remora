"""Turn context assembly for unified agent execution."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.agents.agent_context import AgentContext
from remora.core.agents.agent_node import AgentNode
from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
from remora.core.agents.workspace import CairnDataProvider
from remora.core.code.discovery import CSTNode
from remora.core.events.code_events import ScaffoldRequestEvent
from remora.core.events.interaction_events import AgentMessageEvent
from remora.core.manifest import load_manifest
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.utils import PathResolver
from remora.utils.languages import EXTENSION_TO_LANGUAGE as _LANG_TAGS

if TYPE_CHECKING:
    from remora.core.config import Config
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)


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


@dataclass(slots=True)
class TurnContext:
    bundle_path: Path
    manifest: Any
    model_name: str
    prompt: str
    tools: list[Any]
    chat_history: list[dict[str, str]]
    workspace_service: CairnWorkspaceService
    created_workspace_service: bool


async def build_turn_context(
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
    chat_history: list[dict[str, str]] | None = None,
    load_manifest_fn: Any = load_manifest,
    workspace_service_cls: Any = CairnWorkspaceService,
    data_provider_cls: Any = CairnDataProvider,
    path_resolver_cls: Any = PathResolver,
    discover_grail_tools_fn: Any = discover_grail_tools,
    build_virtual_fs_fn: Any = build_virtual_fs,
    build_prompt_fn: Any = _build_prompt,
) -> TurnContext:
    """Build workspace + prompt + tools for one agent turn."""
    created_workspace_service = False
    try:
        bundle_path = _resolve_bundle_path(node, config)
        manifest = load_manifest_fn(bundle_path)
        logger.info("execute_agent_turn: bundle=%s manifest=%s", bundle_path, getattr(manifest, "name", "?"))

        logger.info("execute_agent_turn: initializing workspace service")
        if workspace_service is None:
            created_workspace_service = True
            workspace_service = workspace_service_cls(
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

        logger.info("execute_agent_turn: building AgentContext")
        correlation_id = getattr(trigger_event, "correlation_id", None) if trigger_event else None
        path_resolver = path_resolver_cls(project_root)

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
                targets = [
                    a.node_id
                    for a in agents
                    if a.parent_id == current_node.parent_id and a.node_id != node.node_id
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

        logger.info("execute_agent_turn: loading workspace files")
        data_provider = data_provider_cls(workspace, path_resolver)
        cst_node = _agent_node_to_cst_node(node)
        files = await data_provider.load_files(cst_node)

        logger.info("execute_agent_turn: loading chat history")
        if chat_history is None:
            recent_events = await event_store.get_agent_timeline(node.node_id, limit=config.chat_history_limit)
            chat_history = []
            for ev in reversed(recent_events):
                payload = ev.get("payload", {})
                event_type = ev.get("event_type")
                if event_type == "AgentMessageEvent":
                    if ev.get("to_agent") == node.node_id:
                        chat_history.append({"role": "user", "content": payload.get("content", "")})
                    elif ev.get("from_agent") == node.node_id:
                        chat_history.append({"role": "assistant", "content": payload.get("content", "")})
                elif event_type == "AgentTextResponse" and ev.get("agent_id") == node.node_id:
                    chat_history.append({"role": "assistant", "content": payload.get("content", "")})

        # Build scaffold context if trigger is ScaffoldRequestEvent
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
        prompt = build_prompt_fn(
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

        logger.info("execute_agent_turn: discovering tools")

        async def files_provider() -> dict[str, str | bytes]:
            current_files = await data_provider.load_files(cst_node)
            fs: dict[str, str | bytes] = dict(build_virtual_fs_fn(current_files))
            return fs

        tools: list[Any] = []
        if manifest.agents_dir:
            tools = discover_grail_tools_fn(
                manifest.agents_dir,
                context=agent_context,
                files_provider=files_provider,
            )

        if extra_tools:
            tools.extend(extra_tools)

        logger.info("execute_agent_turn: %d tools discovered", len(tools))
        model_name = _resolve_model_name(bundle_path, manifest, config)

        return TurnContext(
            bundle_path=bundle_path,
            manifest=manifest,
            model_name=model_name,
            prompt=prompt,
            tools=tools,
            chat_history=chat_history,
            workspace_service=workspace_service,
            created_workspace_service=created_workspace_service,
        )
    except Exception:
        if created_workspace_service and workspace_service is not None:
            try:
                await workspace_service.close()
            except Exception:
                logger.warning("build_turn_context: workspace service close failed", exc_info=True)
        raise


__all__ = [
    "TurnContext",
    "build_turn_context",
    "CairnDataProvider",
    "CairnWorkspaceService",
    "load_manifest",
    "discover_grail_tools",
    "build_virtual_fs",
    "_lang_tag_for",
    "_agent_node_to_cst_node",
    "_resolve_bundle_path",
    "_resolve_model_name",
    "_build_prompt",
]
