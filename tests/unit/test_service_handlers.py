from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.core.config import BundleConfig, RemoraConfig
from remora.core.event_bus import EventBus
from remora.core.events import HumanInputResponseEvent
from remora.models import PlanRequest, RunRequest
from remora.service.handlers import ServiceDeps, handle_input, handle_plan, handle_run
from remora.ui.projector import UiStateProjector


@pytest.mark.asyncio
async def test_handle_input_emits_event() -> None:
    event_bus = EventBus()
    received: list[HumanInputResponseEvent] = []

    def _record(event: object) -> None:
        if isinstance(event, HumanInputResponseEvent):
            received.append(event)

    event_bus.subscribe_all(_record)
    deps = ServiceDeps(
        event_bus=event_bus,
        config=RemoraConfig(),
        project_root=Path.cwd(),
        projector=UiStateProjector(),
        executor_factory=lambda *_args, **_kwargs: None,
        running_tasks={},
    )

    await handle_input("req-1", "ok", deps)
    assert received and received[0].request_id == "req-1"


@pytest.mark.asyncio
async def test_handle_plan_returns_nodes(tmp_path: Path) -> None:
    target_file = tmp_path / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    config = RemoraConfig(bundles=BundleConfig(path=str(tmp_path), mapping={"file": "bundle.pym"}))
    deps = ServiceDeps(
        event_bus=EventBus(),
        config=config,
        project_root=tmp_path,
        projector=UiStateProjector(),
        executor_factory=lambda *_args, **_kwargs: None,
        running_tasks={},
    )

    response = await handle_plan(PlanRequest(target_path=str(tmp_path)), deps)
    assert response.nodes


@pytest.mark.asyncio
async def test_handle_run_starts_task(tmp_path: Path) -> None:
    target_file = tmp_path / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    executed: list[str] = []

    def _factory(*_args, **_kwargs):
        class _Executor:
            async def run(self, _graph, graph_id: str) -> None:
                executed.append(graph_id)

        return _Executor()

    config = RemoraConfig(bundles=BundleConfig(path=str(tmp_path), mapping={"file": "bundle.pym"}))
    deps = ServiceDeps(
        event_bus=EventBus(),
        config=config,
        project_root=tmp_path,
        projector=UiStateProjector(),
        executor_factory=_factory,
        running_tasks={},
    )

    response = await handle_run(RunRequest(target_path=str(target_file)), deps)
    await asyncio.sleep(0)
    if deps.running_tasks:
        await asyncio.gather(*deps.running_tasks.values())
    assert response.status == "started"
    assert executed and executed[0] == response.graph_id
