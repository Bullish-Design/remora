"""Framework-agnostic service handlers for the Remora API."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from remora.core.config import RemoraConfig
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.event_store import EventStore, EventSourcedBus
from remora.core.events import HumanInputResponseEvent
from remora.core.executor import GraphExecutor
from remora.core.graph import AgentNode, build_graph
from remora.models import ConfigSnapshot, InputResponse, PlanRequest, PlanResponse, RunRequest, RunResponse
from remora.ui.projector import UiStateProjector
from remora.utils import PathResolver

logger = logging.getLogger(__name__)

ExecutorFactory = Callable[[RemoraConfig, EventBus, Path], GraphExecutor]


@dataclass(slots=True)
class ServiceDeps:
    event_bus: EventBus
    config: RemoraConfig
    project_root: Path
    projector: UiStateProjector
    executor_factory: ExecutorFactory
    running_tasks: dict[str, asyncio.Task]
    event_store: EventStore | None = None


def default_executor_factory(
    config: RemoraConfig,
    event_bus: EventBus,
    project_root: Path,
) -> GraphExecutor:
    return GraphExecutor(config, event_bus, project_root=project_root)


async def handle_run(request: RunRequest, deps: ServiceDeps) -> RunResponse:
    if not request.target_path:
        raise ValueError("target_path is required")

    bundle_mapping = _build_bundle_mapping(deps.config)
    target_path = _normalize_target(request.target_path, deps.project_root)

    graph_root = target_path if target_path.is_dir() else target_path.parent
    nodes = discover(
        [target_path],
        languages=list(deps.config.discovery.languages) if deps.config.discovery.languages else None,
        max_workers=deps.config.discovery.max_workers,
    )
    agent_nodes = build_graph(nodes, bundle_mapping)

    if request.bundle:
        target_bundle = bundle_mapping.get(request.bundle)
        if target_bundle is None:
            raise ValueError(f"Unknown bundle: {request.bundle}")
        agent_nodes = [node for node in agent_nodes if node.bundle_path == target_bundle]

    graph_id = request.graph_id or uuid.uuid4().hex[:8]
    _record_target(deps.projector, target_path, deps.project_root)

    task = asyncio.create_task(_execute_graph(graph_id, agent_nodes, graph_root, deps))
    deps.running_tasks[graph_id] = task

    def _cleanup(_task: asyncio.Task) -> None:
        deps.running_tasks.pop(graph_id, None)

    task.add_done_callback(_cleanup)

    return RunResponse(graph_id=graph_id, status="started", node_count=len(agent_nodes))


async def handle_input(request_id: str, response: str, deps: ServiceDeps) -> InputResponse:
    if not request_id or not response:
        raise ValueError("request_id and response are required")
    event = HumanInputResponseEvent(request_id=request_id, response=response)
    await deps.event_bus.emit(event)
    return InputResponse(request_id=request_id)


async def handle_plan(request: PlanRequest, deps: ServiceDeps) -> PlanResponse:
    if not request.target_path:
        raise ValueError("target_path is required")

    bundle_mapping = _build_bundle_mapping(deps.config)
    target_path = _normalize_target(request.target_path, deps.project_root)
    nodes = discover(
        [target_path],
        languages=list(deps.config.discovery.languages) if deps.config.discovery.languages else None,
        max_workers=deps.config.discovery.max_workers,
    )
    agent_nodes = build_graph(nodes, bundle_mapping)

    if request.bundle:
        target_bundle = bundle_mapping.get(request.bundle)
        if target_bundle is None:
            raise ValueError(f"Unknown bundle: {request.bundle}")
        agent_nodes = [node for node in agent_nodes if node.bundle_path == target_bundle]

    return PlanResponse(
        nodes=[_serialize_node(node) for node in agent_nodes],
        bundles={key: str(path) for key, path in bundle_mapping.items()},
    )


def handle_config_snapshot(deps: ServiceDeps) -> ConfigSnapshot:
    return ConfigSnapshot.from_config(deps.config)


def handle_ui_snapshot(deps: ServiceDeps) -> dict[str, Any]:
    return deps.projector.snapshot()


def _build_bundle_mapping(config: RemoraConfig) -> dict[str, Path]:
    bundle_root = Path(config.bundles.path)
    mapping = {name: bundle_root / bundle for name, bundle in config.bundles.mapping.items()}
    if not mapping:
        raise ValueError("No bundle mapping configured")
    return mapping


def _normalize_target(target_path: str, project_root: Path) -> Path:
    resolver = PathResolver(project_root)
    path_obj = Path(target_path)
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        resolved = (project_root / path_obj).resolve()
    if not resolver.is_within_project(resolved):
        raise ValueError("target_path must be within the service project root")
    if not resolved.exists():
        raise ValueError("target_path does not exist")
    return resolved


def _record_target(projector: UiStateProjector, target_path: Path, project_root: Path) -> None:
    try:
        rel_target = target_path.relative_to(project_root).as_posix()
    except ValueError:
        rel_target = target_path.as_posix()
    if target_path.is_dir() and not rel_target.endswith("/"):
        rel_target = f"{rel_target}/"
    projector.record_target(rel_target)


def _serialize_node(node: AgentNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "node_type": node.target.node_type,
        "file_path": node.target.file_path,
        "bundle_path": str(node.bundle_path),
        "upstream": list(node.upstream),
        "downstream": list(node.downstream),
        "priority": node.priority,
    }


async def _execute_graph(graph_id: str, agent_nodes: list[AgentNode], project_root: Path, deps: ServiceDeps) -> None:
    try:
        event_bus: EventBus = deps.event_bus
        if deps.event_store is not None:
            event_bus = EventSourcedBus(deps.event_bus, deps.event_store, graph_id)  # type: ignore[assignment]
        executor = deps.executor_factory(deps.config, event_bus, project_root)
        await executor.run(agent_nodes, graph_id)
    except Exception:
        logger.exception("Graph execution failed: %s", graph_id)


__all__ = [
    "ServiceDeps",
    "default_executor_factory",
    "handle_config_snapshot",
    "handle_input",
    "handle_plan",
    "handle_run",
    "handle_ui_snapshot",
]
