from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from remora.bootstrap.bedrock import BootstrapEvent
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
    assert runner.subscriptions_path == tmp_path / ".remora" / "subscriptions.db"


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
    emit_mock = AsyncMock()
    handle_mock = AsyncMock(return_value=SimpleNamespace(node_id="module:src/app.py", agent_id="agent-app"))
    monkeypatch.setattr("remora.bootstrap.runner.find_unassigned_nodes", find_mock)
    monkeypatch.setattr("remora.bootstrap.runner.handle_agent_needed", handle_mock)

    runner = BootstrapRunner(config, bootstrap_root=bootstrap_root)
    try:
        await runner.initialize()
        monkeypatch.setattr(runner, "_emit_events_for_plans", emit_mock)
        event_store_ref = runner.event_store
        handled = await runner.run_once()
    finally:
        await runner.close()

    assert handled == 1
    emit_mock.assert_awaited_once()
    find_mock.assert_awaited_once_with(event_store_ref, node_types={"file"})
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
    monkeypatch.setattr("remora.bootstrap.runner.find_unassigned_nodes", AsyncMock(return_value=[]))
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


@pytest.mark.asyncio
async def test_run_for_file_fans_out_unassigned_nodes(
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

    plans = [
        AgentNeededPlan(node_id="module:src/app.py", agent_id="agent-app"),
        AgentNeededPlan(node_id="function:src/app.py:build_app", agent_id="agent-build-app"),
    ]
    find_nodes_mock = AsyncMock(return_value=plans)
    emit_mock = AsyncMock()
    handle_mock = AsyncMock(return_value=SimpleNamespace())

    monkeypatch.setattr("remora.bootstrap.runner.find_unassigned_nodes", find_nodes_mock)
    monkeypatch.setattr("remora.bootstrap.runner.handle_agent_needed", handle_mock)

    runner = BootstrapRunner(config, bootstrap_root=bootstrap_root)
    event_store_ref = None
    try:
        await runner.initialize()
        monkeypatch.setattr(runner, "_emit_events_for_plans", emit_mock)
        event_store_ref = runner.event_store
        handled = await runner.run_for_file("src/app.py")
    finally:
        await runner.close()

    assert handled == 2
    assert event_store_ref is not None
    find_nodes_mock.assert_awaited_once_with(
        event_store_ref,
        file_path="src/app.py",
        node_types={"file"},
    )
    emit_mock.assert_awaited_once_with(plans)
    assert handle_mock.await_count == 2

    handled_node_ids = {
        call.args[0].payload["node_id"]
        for call in handle_mock.await_args_list
    }
    assert handled_node_ids == {"module:src/app.py", "function:src/app.py:build_app"}


@pytest.mark.asyncio
async def test_handle_human_input_response_appends_event_and_reactivates_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config(tmp_path)
    bootstrap_root = tmp_path / "bootstrap"
    (bootstrap_root / "tools").mkdir(parents=True)
    (bootstrap_root / "agents").mkdir(parents=True)

    monkeypatch.setattr("remora.bootstrap.runner.seed_coordinator_node", AsyncMock())
    monkeypatch.setattr("remora.bootstrap.runner.seed_modules_if_empty", AsyncMock(return_value=0))
    monkeypatch.setattr("remora.bootstrap.runner.CairnWorkspaceService", _FakeWorkspaceService)
    handle_mock = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr("remora.bootstrap.runner.handle_agent_needed", handle_mock)

    event_store = SimpleNamespace(append=AsyncMock(return_value=7))
    subscriptions = SimpleNamespace()
    workspace_service = _FakeWorkspaceService()
    runner = BootstrapRunner(
        config,
        bootstrap_root=bootstrap_root,
        event_store=event_store,
        subscriptions=subscriptions,
        workspace_service=workspace_service,
    )
    try:
        handled = await runner.handle_human_input_response(
            agent_id="agent-app",
            node_id="module:src/app.py",
            request_id="req-1",
            response="Use the cache layer.",
            question="How should this node behave?",
        )
    finally:
        await runner.close()

    assert handled is True
    event_store.append.assert_awaited_once()
    append_swarm_id, appended_event = event_store.append.await_args.args
    assert append_swarm_id == "bootstrap-test"
    assert isinstance(appended_event, BootstrapEvent)
    assert appended_event.event_type == "HumanInputResponseEvent"
    assert appended_event.to_agent == "agent-app"
    assert appended_event.payload["request_id"] == "req-1"
    assert appended_event.payload["response"] == "Use the cache layer."

    handle_mock.assert_awaited_once()
    activation_event = handle_mock.await_args.args[0]
    assert isinstance(activation_event, BootstrapEvent)
    assert activation_event.event_type == "HumanInputResponseEvent"


@pytest.mark.asyncio
async def test_run_once_uses_configured_node_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _make_config(tmp_path)
    monkeypatch.setattr("remora.bootstrap.runner.CairnWorkspaceService", _FakeWorkspaceService)
    monkeypatch.setattr("remora.bootstrap.runner.seed_coordinator_node", AsyncMock())
    monkeypatch.setattr("remora.bootstrap.runner.seed_modules_if_empty", AsyncMock(return_value=0))
    find_nodes_mock = AsyncMock(return_value=[])
    monkeypatch.setattr("remora.bootstrap.runner.find_unassigned_nodes", find_nodes_mock)

    runner = BootstrapRunner(config, node_types={"function"})
    try:
        await runner.run_once()
        event_store_ref = runner.event_store
    finally:
        await runner.close()

    find_nodes_mock.assert_awaited_once_with(event_store_ref, node_types={"function"})
