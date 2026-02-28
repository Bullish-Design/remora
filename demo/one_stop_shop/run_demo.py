#!/usr/bin/env python3
"""One stop shop demo for Remora running against a real project."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from remora.core.cairn_bridge import CairnWorkspaceService, SyncMode
from remora.core.config import load_config
from remora.core.context import ContextBuilder
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.events import AgentCompleteEvent, AgentErrorEvent
from remora.core.executor import GraphExecutor
from remora.core.graph import build_graph

DEMO_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DEMO_ROOT / "project"
OUTPUT_DIR = DEMO_ROOT / "outputs"
CONFIG_PATH = DEMO_ROOT / "remora.yaml"


def _ensure_project_on_path() -> None:
    src_path = PROJECT_ROOT / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def _event_record(event: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"type": type(event).__name__}
    if is_dataclass(event):
        record.update(asdict(event))
    elif hasattr(event, "__dict__"):
        record.update({k: v for k, v in vars(event).items() if not k.startswith("_")})
    else:
        record["repr"] = repr(event)
    return record


async def _log_events(bus: EventBus, output_path: Path, stop_event: asyncio.Event) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        async with bus.stream() as events:
            async for event in events:
                handle.write(json.dumps(_event_record(event)) + "\n")
                handle.flush()
                if stop_event.is_set():
                    break


def _print_event(event: Any) -> None:
    if isinstance(event, AgentCompleteEvent):
        print(f"Agent {event.agent_id} completed")
    elif isinstance(event, AgentErrorEvent):
        print(f"Agent {event.agent_id} failed: {event.error}")


def _run_meridian_pipeline(output_path: Path) -> None:
    _ensure_project_on_path()
    from meridian.io.exporter import write_plan
    from meridian.io.loader import load_dataset
    from meridian.pipeline import MeridianPlanner

    dataset = load_dataset(PROJECT_ROOT / "data")
    planner = MeridianPlanner()
    plan = planner.plan(dataset)
    write_plan(plan, output_path)

    print("Meridian plan generated")
    print(f"Meridian output: {output_path}")


async def _inspect_workspace(
    config_path: Path,
    graph_id: str,
    agent_id: str,
    target_path: str,
) -> None:
    config = load_config(config_path)
    service = CairnWorkspaceService(config.workspace, graph_id, project_root=PROJECT_ROOT)
    await service.initialize(sync_mode=SyncMode.NONE)

    try:
        workspace = await service.get_agent_workspace(agent_id)
        workspace_path = service.resolver.to_workspace_path(target_path)
        try:
            contents = await workspace.read(workspace_path)
        except Exception as exc:
            print("Workspace inspection failed")
            print(f"- Agent: {agent_id}")
            print(f"- Workspace path: {workspace_path}")
            print(f"- Error: {exc}")
            return
        snippet = contents.splitlines()[:12]
        print("Workspace inspection")
        print(f"- Agent: {agent_id}")
        print(f"- Workspace path: {workspace_path}")
        if snippet:
            print("- File preview:")
            for line in snippet:
                print(f"  {line}")
        else:
            print("- File preview: empty")
    finally:
        await service.close()


def _resolve_paths(config) -> tuple[list[str], Path]:
    repo_root = DEMO_ROOT.parents[1]
    discovery_paths: list[str] = []
    for path in config.discovery.paths:
        path_obj = Path(path)
        if not path_obj.is_absolute():
            path_obj = repo_root / path_obj
        discovery_paths.append(str(path_obj.resolve()))

    bundle_root = Path(config.bundles.path)
    if not bundle_root.is_absolute():
        bundle_root = (repo_root / bundle_root).resolve()

    return discovery_paths, bundle_root


async def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    meridian_output = OUTPUT_DIR / "meridian_plan.json"
    _run_meridian_pipeline(meridian_output)

    config = load_config(CONFIG_PATH)
    discovery_paths, bundle_root = _resolve_paths(config)

    nodes = discover(
        discovery_paths,
        languages=list(config.discovery.languages) if config.discovery.languages else None,
        max_workers=config.discovery.max_workers,
    )

    bundle_mapping = {
        node_type: bundle_root / bundle
        for node_type, bundle in config.bundles.mapping.items()
    }

    graph = build_graph(nodes, bundle_mapping)

    event_bus = EventBus()
    context_builder = ContextBuilder(window_size=12)
    event_bus.subscribe_all(_print_event)

    executor = GraphExecutor(
        config=config,
        event_bus=event_bus,
        context_builder=context_builder,
        project_root=PROJECT_ROOT,
    )

    stop_event = asyncio.Event()
    log_task = asyncio.create_task(
        _log_events(event_bus, OUTPUT_DIR / "remora_events.jsonl", stop_event)
    )

    graph_id = "one-stop-shop"
    results = await executor.run(graph, graph_id)

    stop_event.set()
    log_task.cancel()
    try:
        await log_task
    except asyncio.CancelledError:
        pass

    print(f"Completed {len(results)} agents")
    print(f"Knowledge entries: {len(context_builder.get_knowledge())}")

    if graph:
        target = graph[0]
        await _inspect_workspace(CONFIG_PATH, graph_id, target.id, target.target.file_path)


if __name__ == "__main__":
    asyncio.run(main())
