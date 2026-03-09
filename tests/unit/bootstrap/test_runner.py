from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from remora.bootstrap.coordinator import AgentNeededPlan
from remora.bootstrap.runner import BootstrapRunner
from remora.core.config import Config


class _FakeWorkspaceService:
    def __init__(self, *_args, **_kwargs) -> None:
        self.close = AsyncMock()


def _make_config(tmp_path: Path) -> Config:
    return Config(
        project_path=str(tmp_path / "project"),
        swarm_root=str(tmp_path / ".remora"),
        swarm_id="bootstrap-test",
        model_base_url="http://localhost:8000/v1",
        model_default="Qwen/Qwen3-4B",
        model_api_key="",
        timeout_s=30.0,
    )


def test_runner_default_paths_use_existing_event_store_layout(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = BootstrapRunner(config)

    assert runner.event_store_path == tmp_path / ".remora" / "events" / "events.db"
    assert runner.subscriptions_path == tmp_path / ".remora" / "events" / "subscriptions.db"


@pytest.mark.asyncio
async def test_run_once_emits_and_handles_unassigned_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config(tmp_path)
    bootstrap_root = tmp_path / "bootstrap"
    (bootstrap_root / "tools").mkdir(parents=True)
    (bootstrap_root / "agents").mkdir(parents=True)

    monkeypatch.setattr("remora.bootstrap.runner.CairnWorkspaceService", _FakeWorkspaceService)
    monkeypatch.setattr("remora.bootstrap.runner.seed_coordinator_node", AsyncMock())
    monkeypatch.setattr("remora.bootstrap.runner.seed_modules_if_empty", AsyncMock(return_value=0))

    plans = [AgentNeededPlan(node_id="module:src/app.py", agent_id="agent-app")]
    find_mock = AsyncMock(return_value=plans)
    emit_mock = AsyncMock(return_value=1)
    handle_mock = AsyncMock(return_value=SimpleNamespace(node_id="module:src/app.py", agent_id="agent-app"))
    monkeypatch.setattr("remora.bootstrap.runner.find_unassigned_modules", find_mock)
    monkeypatch.setattr("remora.bootstrap.runner.emit_agent_needed_events", emit_mock)
    monkeypatch.setattr("remora.bootstrap.runner.handle_agent_needed", handle_mock)

    runner = BootstrapRunner(config, bootstrap_root=bootstrap_root)
    try:
        await runner.initialize()
        handled = await runner.run_once()
    finally:
        await runner.close()

    assert handled == 1
    emit_mock.assert_awaited_once()
    find_mock.assert_awaited_once()
    handle_mock.assert_awaited_once()
    activation_event = handle_mock.await_args.args[0]
    assert activation_event.event_type == "AgentNeededEvent"
    assert activation_event.payload["agent_id"] == "agent-app"
    assert activation_event.payload["node_id"] == "module:src/app.py"


@pytest.mark.asyncio
async def test_run_forever_stops_when_stop_called(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config(tmp_path)
    monkeypatch.setattr("remora.bootstrap.runner.CairnWorkspaceService", _FakeWorkspaceService)
    monkeypatch.setattr("remora.bootstrap.runner.seed_coordinator_node", AsyncMock())
    monkeypatch.setattr("remora.bootstrap.runner.seed_modules_if_empty", AsyncMock(return_value=0))
    monkeypatch.setattr("remora.bootstrap.runner.find_unassigned_modules", AsyncMock(return_value=[]))
    monkeypatch.setattr("remora.bootstrap.runner.emit_agent_needed_events", AsyncMock(return_value=0))
    monkeypatch.setattr("remora.bootstrap.runner.handle_agent_needed", AsyncMock())

    runner = BootstrapRunner(config)
    calls = 0

    async def _fake_run_once() -> int:
        nonlocal calls
        calls += 1
        runner.stop()
        return 0

    monkeypatch.setattr(runner, "run_once", _fake_run_once)

    try:
        await runner.run_forever(poll_interval_s=0.0)
    finally:
        await runner.close()

    assert calls == 1
