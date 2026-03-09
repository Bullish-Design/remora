"""Bootstrap activation handlers for self-bootstrapping agents."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora.bootstrap.bedrock import BootstrapEvent, build_bedrock, extract_workspace_tools, make_files_provider
from remora.bootstrap.schema_loader import TurnSchema, load_schema
from remora.bootstrap.turn_executor import TurnExecutor, TurnResult
from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
from remora.core.agents.cairn_externals import CairnExternals
from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.core.store.event_store import EventStore
from remora.core.tools.grail import discover_grail_tools

logger = logging.getLogger(__name__)


@dataclass
class ActivationResult:
    agent_id: str
    node_id: str
    turn: TurnResult


def default_agent_id(node_id: str) -> str:
    """Create a stable, filesystem-safe agent ID from a node ID."""
    digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:10]
    safe_tail = re.sub(r"[^a-zA-Z0-9_.-]+", "-", node_id).strip("-")
    if not safe_tail:
        safe_tail = "node"
    safe_tail = safe_tail[-40:]
    return f"agent-{safe_tail}-{digest}"


def _resolve_node_vars(text: str, node_attrs: dict[str, Any]) -> str:
    def replacer(match: re.Match[str]) -> str:
        return str(node_attrs.get(match.group(1), match.group(0)))

    return re.sub(r"\{node\.([^}]+)\}", replacer, text)


async def _read_node_attrs(event_store: EventStore, node_id: str) -> dict[str, Any]:
    node_raw = await event_store.nodes.read_graph({"node": node_id})
    node_data = json.loads(node_raw) if node_raw else None
    if not isinstance(node_data, dict):
        return {"id": node_id, "node_id": node_id}

    attrs = node_data.get("attrs")
    if not isinstance(attrs, dict):
        attrs = {}
    attrs = dict(attrs)
    attrs.setdefault("id", node_id)
    attrs.setdefault("node_id", node_id)
    return attrs


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _build_subject_matter_expert_schema(*, agent_id: str) -> str:
    return (
        'version: "1"\n'
        f'name: "{agent_id}_sme"\n'
        "extends: subject_matter_expert\n"
        'termination: "DONE"\n'
    )


def _build_summary_template(node_attrs: dict[str, Any]) -> str:
    node_name = str(
        node_attrs.get("full_name")
        or node_attrs.get("name")
        or node_attrs.get("id")
        or node_attrs.get("node_id")
        or "unknown-node"
    )
    return (
        f"# Node Guide: {node_name}\n\n"
        "## What I am\n"
        "_pending_\n\n"
        "## What I do\n"
        "_pending_\n\n"
        "## How I do it\n"
        "_pending_\n\n"
        "## Known limitations\n"
        "_pending_\n\n"
        "## User questions and answers\n"
        "_none yet_\n\n"
        "## User corrections\n"
        "_none yet_\n"
    )


async def _ensure_subject_matter_expert_workspace(
    cairn_externals: CairnExternals,
    *,
    agent_id: str,
    node_attrs: dict[str, Any],
) -> None:
    read_file = getattr(cairn_externals, "read_file", None)
    write_file = getattr(cairn_externals, "write_file", None)
    if not callable(read_file) or not callable(write_file):
        return

    try:
        schema_text = _as_text(await read_file("schema.yaml"))
    except Exception:
        schema_text = ""
    if not schema_text.strip():
        await write_file("schema.yaml", _build_subject_matter_expert_schema(agent_id=agent_id))

    try:
        summary_text = _as_text(await read_file("summary.md"))
    except Exception:
        summary_text = ""
    if not summary_text.strip():
        await write_file("summary.md", _build_summary_template(node_attrs))


def _extract_human_response_fields(activation_event: Any) -> tuple[str, str, str]:
    event_type = getattr(activation_event, "event_type", "")
    payload = getattr(activation_event, "payload", {}) if activation_event is not None else {}
    if not isinstance(payload, dict):
        payload = {}
    if event_type != "HumanInputResponseEvent":
        return "", "", ""

    request_id = str(payload.get("request_id", "")).strip()
    response = str(payload.get("response", "")).strip()
    question = str(payload.get("question", "")).strip()
    return request_id, question, response


async def _append_correction_notes(
    cairn_externals: CairnExternals,
    *,
    request_id: str,
    question: str,
    response: str,
) -> None:
    if not response:
        return

    marker_id = request_id or "no-request-id"
    notes_entry = (
        f"- Correction `{marker_id}`: {response}"
        + (f" (question: {question})" if question else "")
        + "\n"
    )
    summary_entry = (
        f"- `{marker_id}`: {response}"
        + (f" (question: {question})" if question else "")
        + "\n"
    )

    try:
        notes_text = _as_text(await cairn_externals.read_file("notes.md"))
    except Exception:
        notes_text = ""
    if notes_entry not in notes_text:
        if notes_text and not notes_text.endswith("\n"):
            notes_text += "\n"
        notes_text += notes_entry
        await cairn_externals.write_file("notes.md", notes_text)

    try:
        summary_text = _as_text(await cairn_externals.read_file("summary.md"))
    except Exception:
        summary_text = ""
    if summary_entry in summary_text:
        return

    section = "## User corrections"
    if section not in summary_text:
        if summary_text and not summary_text.endswith("\n"):
            summary_text += "\n"
        summary_text += f"\n{section}\n"
    if not summary_text.endswith("\n"):
        summary_text += "\n"
    summary_text += summary_entry
    await cairn_externals.write_file("summary.md", summary_text)


async def _list_workspace_tool_files(cairn_externals: CairnExternals) -> set[str]:
    try:
        files = await cairn_externals.list_dir("tools")
    except Exception:
        return set()
    return {name for name in (files or []) if name.endswith(".pym")}


async def _emit_tool_synthesized_events(
    event_store: EventStore,
    *,
    swarm_id: str,
    agent_id: str,
    node_id: str,
    before: set[str],
    after: set[str],
) -> int:
    emitted = 0
    for file_name in sorted(after - before):
        event = BootstrapEvent(
            event_type="ToolSynthesizedEvent",
            node_id=node_id,
            payload={
                "node_id": node_id,
                "agent_id": agent_id,
                "tool_name": Path(file_name).stem,
                "file_path": f"tools/{file_name}",
            },
            from_agent=agent_id,
            tags=("bootstrap", "tool-synthesized"),
        )
        await event_store.append(swarm_id, event)
        emitted += 1
    return emitted


def _pattern_key(pattern: SubscriptionPattern) -> tuple[Any, ...]:
    return (
        tuple(pattern.event_types or []),
        tuple(pattern.from_agents or []),
        pattern.to_agent,
        pattern.path_glob,
        tuple(pattern.tags or []),
    )


async def _ensure_direct_subscription(subscriptions: SubscriptionRegistry, agent_id: str) -> None:
    existing = await subscriptions.get_subscriptions(agent_id)
    if any(sub.pattern.to_agent == agent_id for sub in existing):
        return
    await subscriptions.register(
        agent_id,
        SubscriptionPattern(to_agent=agent_id),
        is_default=True,
    )


async def _register_schema_subscriptions(
    subscriptions: SubscriptionRegistry,
    *,
    agent_id: str,
    schema: TurnSchema,
    node_attrs: dict[str, Any],
) -> int:
    """Register event-type subscriptions declared in schema.yaml.

    NOTE: v1 SubscriptionPattern has no node_id selector, so schema node_id
    fields are currently informational and ignored here.
    """
    existing = await subscriptions.get_subscriptions(agent_id)
    known = {_pattern_key(sub.pattern) for sub in existing}
    created = 0

    for spec in schema.subscriptions:
        event_type = _resolve_node_vars(spec.event_type, node_attrs)
        if not event_type:
            continue

        if spec.node_id:
            logger.debug(
                "Ignoring schema node_id subscription filter for %s: %s",
                agent_id,
                _resolve_node_vars(spec.node_id, node_attrs),
            )

        pattern = SubscriptionPattern(event_types=[event_type])
        key = _pattern_key(pattern)
        if key in known:
            continue

        await subscriptions.register(agent_id, pattern)
        known.add(key)
        created += 1

    return created


async def handle_agent_needed(
    event: Any,
    *,
    workspace_service: CairnWorkspaceService,
    subscriptions: SubscriptionRegistry,
    event_store: EventStore,
    config: Any,
    swarm_id: str,
    bootstrap_root: Path | None = None,
) -> ActivationResult:
    """Handle an AgentNeededEvent by creating/running the target agent."""
    payload = getattr(event, "payload", {}) or {}
    if not isinstance(payload, dict):
        payload = {}

    raw_node_id = payload.get("node_id") or getattr(event, "node_id", None)
    if raw_node_id is None:
        raise ValueError("AgentNeededEvent requires payload.node_id")

    node_id = str(raw_node_id)
    agent_id = str(payload.get("agent_id") or default_agent_id(node_id))

    root = bootstrap_root or Path("bootstrap")
    tools_dir = root / "tools"
    agents_dir = root / "agents"

    await workspace_service.initialize(sync_mode=SyncMode.NONE)
    workspace = await workspace_service.get_agent_workspace(agent_id)

    stable_workspace = getattr(workspace_service, "_stable_workspace", None)
    if stable_workspace is None:
        raise RuntimeError("Workspace service stable workspace is not initialized")

    cairn_externals = CairnExternals(
        agent_id=agent_id,
        agent_fs=workspace.cairn,
        stable_fs=stable_workspace,
        resolver=workspace_service.resolver,
    )

    await _ensure_direct_subscription(subscriptions, agent_id)

    bedrock = build_bedrock(
        agent_id=agent_id,
        cairn_externals=cairn_externals,
        event_store=event_store,
        swarm_id=swarm_id,
    )
    files_provider = await make_files_provider(cairn_externals)

    node_attrs = await _read_node_attrs(event_store, node_id)
    await _ensure_subject_matter_expert_workspace(
        cairn_externals,
        agent_id=agent_id,
        node_attrs=node_attrs,
    )
    request_id, question, response = _extract_human_response_fields(event)
    await _append_correction_notes(
        cairn_externals,
        request_id=request_id,
        question=question,
        response=response,
    )
    tool_files_before = await _list_workspace_tool_files(cairn_externals)

    with tempfile.TemporaryDirectory(prefix="remora-bootstrap-") as tmp_dir:
        extracted_tools_dir = await extract_workspace_tools(cairn_externals, Path(tmp_dir))
        tools = discover_grail_tools(
            tools_dir,
            context=None,
            externals=bedrock,
            files_provider=files_provider,
            workspace_tools_dir=extracted_tools_dir,
        )

        executor = TurnExecutor(
            agent_id=agent_id,
            cairn_externals=cairn_externals,
            tools=tools,
            node_attrs=node_attrs,
            config=config,
            system_agents_dir=agents_dir,
        )
        turn = await executor.run(event)

    tool_files_after = await _list_workspace_tool_files(cairn_externals)
    await _emit_tool_synthesized_events(
        event_store,
        swarm_id=swarm_id,
        agent_id=agent_id,
        node_id=node_id,
        before=tool_files_before,
        after=tool_files_after,
    )

    schema = await load_schema(cairn_externals, system_agents_dir=agents_dir)
    await _register_schema_subscriptions(
        subscriptions,
        agent_id=agent_id,
        schema=schema,
        node_attrs=node_attrs,
    )

    await event_store.nodes.write_graph(
        "add_node",
        {
            "id": agent_id,
            "kind": "agent",
            "attrs": {
                "name": agent_id,
                "assigned_node_id": node_id,
                "status": "active",
            },
        },
    )
    await event_store.nodes.write_graph(
        "add_edge",
        {
            "from": agent_id,
            "to": node_id,
            "kind": "assigned_to",
        },
    )

    return ActivationResult(agent_id=agent_id, node_id=node_id, turn=turn)


__all__ = [
    "ActivationResult",
    "default_agent_id",
    "handle_agent_needed",
]
