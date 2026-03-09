from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from remora.bootstrap.activation import (
    _append_correction_notes,
    _ensure_subject_matter_expert_workspace,
    _extract_human_response_fields,
    default_agent_id,
    handle_agent_needed,
)
from remora.bootstrap.bedrock import BootstrapEvent
from remora.bootstrap.schema_loader import SubscriptionSpec, TurnSchema
from remora.bootstrap.turn_executor import TurnResult
from remora.core.events.subscriptions import SubscriptionPattern


class _FakeExecutor:
    instances: list[_FakeExecutor] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.run_calls: list[object] = []
        _FakeExecutor.instances.append(self)

    async def run(self, event: object):
        self.run_calls.append(event)
        return TurnResult(response_text="DONE", context_values={"ctx": "value"})


@pytest.mark.asyncio
async def test_handle_agent_needed_bootstraps_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bootstrap_root = tmp_path / "bootstrap"
    (bootstrap_root / "tools").mkdir(parents=True)
    (bootstrap_root / "agents").mkdir(parents=True)

    class FakeCairnExternals:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    async def _fake_files_provider(_cairn_ext):
        async def _provider():
            return {}

        return _provider

    async def _fake_extract(_cairn_ext, tmp_dir: Path) -> Path:
        return tmp_dir

    monkeypatch.setattr("remora.bootstrap.activation.CairnExternals", FakeCairnExternals)
    monkeypatch.setattr("remora.bootstrap.activation._make_files_provider", _fake_files_provider)
    monkeypatch.setattr("remora.bootstrap.activation._extract_workspace_tools", _fake_extract)
    monkeypatch.setattr("remora.bootstrap.activation.TurnExecutor", _FakeExecutor)
    monkeypatch.setattr("remora.bootstrap.activation.build_bedrock", lambda **_: {"graph_read": object()})
    monkeypatch.setattr("remora.bootstrap.activation.discover_grail_tools", lambda *_, **__: [])

    async def _fake_load_schema(*args, **kwargs):
        return TurnSchema(
            name="child",
            subscriptions=[
                SubscriptionSpec(event_type="ContentChangedEvent", node_id="{node.id}"),
            ],
        )

    monkeypatch.setattr("remora.bootstrap.activation.load_schema", _fake_load_schema)

    workspace = SimpleNamespace(cairn=object())
    workspace_service = SimpleNamespace(
        _stable_workspace=object(),
        resolver=object(),
        initialize=AsyncMock(),
        get_agent_workspace=AsyncMock(return_value=workspace),
    )

    subscriptions = SimpleNamespace(
        get_subscriptions=AsyncMock(side_effect=[[], []]),
        register=AsyncMock(),
    )

    event_store = SimpleNamespace(
        nodes=SimpleNamespace(
            read_graph=AsyncMock(
                return_value=json.dumps(
                    {
                        "id": "module:src/app.py",
                        "kind": "module",
                        "attrs": {
                            "id": "module:src/app.py",
                            "full_name": "src.app",
                            "file_path": "src/app.py",
                        },
                    }
                )
            ),
            write_graph=AsyncMock(return_value="{}"),
        )
    )

    event = SimpleNamespace(
        event_type="AgentNeededEvent",
        node_id="module:src/app.py",
        payload={
            "node_id": "module:src/app.py",
            "agent_id": "agent-app",
        },
    )

    config = SimpleNamespace(
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
        model_default="Qwen/Qwen3-4B",
        timeout_s=30.0,
    )

    result = await handle_agent_needed(
        event,
        workspace_service=workspace_service,
        subscriptions=subscriptions,
        event_store=event_store,
        config=config,
        swarm_id="swarm",
        bootstrap_root=bootstrap_root,
    )

    assert result.agent_id == "agent-app"
    assert result.node_id == "module:src/app.py"
    assert result.turn.response_text == "DONE"

    workspace_service.initialize.assert_awaited_once()
    workspace_service.get_agent_workspace.assert_awaited_once_with("agent-app")

    assert subscriptions.register.await_count == 2
    first_pattern = subscriptions.register.await_args_list[0].args[1]
    second_pattern = subscriptions.register.await_args_list[1].args[1]
    assert isinstance(first_pattern, SubscriptionPattern)
    assert first_pattern.to_agent == "agent-app"
    assert isinstance(second_pattern, SubscriptionPattern)
    assert second_pattern.event_types == ["ContentChangedEvent"]

    add_node_call = event_store.nodes.write_graph.await_args_list[0]
    assert add_node_call.args[0] == "add_node"
    assert add_node_call.args[1]["id"] == "agent-app"
    assert add_node_call.args[1]["attrs"]["assigned_node_id"] == "module:src/app.py"

    add_edge_call = event_store.nodes.write_graph.await_args_list[1]
    assert add_edge_call.args[0] == "add_edge"
    assert add_edge_call.args[1]["from"] == "agent-app"
    assert add_edge_call.args[1]["to"] == "module:src/app.py"


@pytest.mark.asyncio
async def test_handle_agent_needed_generates_agent_id_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bootstrap_root = tmp_path / "bootstrap"
    (bootstrap_root / "tools").mkdir(parents=True)
    (bootstrap_root / "agents").mkdir(parents=True)

    class FakeCairnExternals:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("remora.bootstrap.activation.CairnExternals", FakeCairnExternals)
    monkeypatch.setattr("remora.bootstrap.activation._make_files_provider", AsyncMock(return_value=AsyncMock(return_value={})))
    monkeypatch.setattr("remora.bootstrap.activation._extract_workspace_tools", AsyncMock(return_value=tmp_path))
    monkeypatch.setattr("remora.bootstrap.activation.TurnExecutor", _FakeExecutor)
    monkeypatch.setattr("remora.bootstrap.activation.build_bedrock", lambda **_: {"graph_read": object()})
    monkeypatch.setattr("remora.bootstrap.activation.discover_grail_tools", lambda *_, **__: [])
    monkeypatch.setattr("remora.bootstrap.activation.load_schema", AsyncMock(return_value=TurnSchema()))

    workspace = SimpleNamespace(cairn=object())
    workspace_service = SimpleNamespace(
        _stable_workspace=object(),
        resolver=object(),
        initialize=AsyncMock(),
        get_agent_workspace=AsyncMock(return_value=workspace),
    )

    subscriptions = SimpleNamespace(
        get_subscriptions=AsyncMock(return_value=[]),
        register=AsyncMock(),
    )

    event_store = SimpleNamespace(
        nodes=SimpleNamespace(
            read_graph=AsyncMock(return_value=json.dumps({"id": "module:src/app.py", "attrs": {}})),
            write_graph=AsyncMock(return_value="{}"),
        )
    )

    event = SimpleNamespace(
        event_type="AgentNeededEvent",
        node_id="module:src/app.py",
        payload={"node_id": "module:src/app.py"},
    )

    config = SimpleNamespace(
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
        model_default="Qwen/Qwen3-4B",
        timeout_s=30.0,
    )

    result = await handle_agent_needed(
        event,
        workspace_service=workspace_service,
        subscriptions=subscriptions,
        event_store=event_store,
        config=config,
        swarm_id="swarm",
        bootstrap_root=bootstrap_root,
    )

    assert result.agent_id == default_agent_id("module:src/app.py")


def test_default_agent_id_is_stable_and_safe() -> None:
    node_id = "module:src/remora/core/events/events.py"
    first = default_agent_id(node_id)
    second = default_agent_id(node_id)

    assert first == second
    assert first.startswith("agent-")
    assert "/" not in first
    assert ":" not in first


@pytest.mark.asyncio
async def test_handle_agent_needed_emits_tool_synthesized_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bootstrap_root = tmp_path / "bootstrap"
    (bootstrap_root / "tools").mkdir(parents=True)
    (bootstrap_root / "agents").mkdir(parents=True)

    class FakeCairnExternals:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("remora.bootstrap.activation.CairnExternals", FakeCairnExternals)
    monkeypatch.setattr("remora.bootstrap.activation._make_files_provider", AsyncMock(return_value=AsyncMock(return_value={})))
    monkeypatch.setattr("remora.bootstrap.activation._extract_workspace_tools", AsyncMock(return_value=tmp_path))
    monkeypatch.setattr("remora.bootstrap.activation.TurnExecutor", _FakeExecutor)
    monkeypatch.setattr("remora.bootstrap.activation.build_bedrock", lambda **_: {"graph_read": object()})
    monkeypatch.setattr("remora.bootstrap.activation.discover_grail_tools", lambda *_, **__: [])
    monkeypatch.setattr(
        "remora.bootstrap.activation._list_workspace_tool_files",
        AsyncMock(side_effect=[set(), {"node_context.pym"}]),
    )
    monkeypatch.setattr("remora.bootstrap.activation.load_schema", AsyncMock(return_value=TurnSchema()))

    workspace = SimpleNamespace(cairn=object())
    workspace_service = SimpleNamespace(
        _stable_workspace=object(),
        resolver=object(),
        initialize=AsyncMock(),
        get_agent_workspace=AsyncMock(return_value=workspace),
    )
    subscriptions = SimpleNamespace(
        get_subscriptions=AsyncMock(return_value=[]),
        register=AsyncMock(),
    )
    event_store = SimpleNamespace(
        nodes=SimpleNamespace(
            read_graph=AsyncMock(return_value=json.dumps({"id": "module:src/app.py", "attrs": {}})),
            write_graph=AsyncMock(return_value="{}"),
        ),
        append=AsyncMock(return_value=11),
    )
    event = SimpleNamespace(
        event_type="AgentNeededEvent",
        node_id="module:src/app.py",
        payload={"node_id": "module:src/app.py", "agent_id": "agent-app"},
    )
    config = SimpleNamespace(
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
        model_default="Qwen/Qwen3-4B",
        timeout_s=30.0,
    )

    await handle_agent_needed(
        event,
        workspace_service=workspace_service,
        subscriptions=subscriptions,
        event_store=event_store,
        config=config,
        swarm_id="swarm",
        bootstrap_root=bootstrap_root,
    )

    event_store.append.assert_awaited_once()
    append_args = event_store.append.await_args.args
    assert append_args[0] == "swarm"
    emitted = append_args[1]
    assert isinstance(emitted, BootstrapEvent)
    assert emitted.event_type == "ToolSynthesizedEvent"
    assert emitted.payload["tool_name"] == "node_context"


@pytest.mark.asyncio
async def test_ensure_subject_matter_expert_workspace_seeds_schema_and_summary() -> None:
    class _FakeCairnExternals:
        def __init__(self) -> None:
            self.files: dict[str, str] = {}

        async def read_file(self, path: str) -> str:
            return self.files.get(path, "")

        async def write_file(self, path: str, content: str) -> None:
            self.files[path] = content

    cairn = _FakeCairnExternals()
    await _ensure_subject_matter_expert_workspace(
        cairn,
        agent_id="agent-app",
        node_attrs={"id": "module:src/app.py", "full_name": "src.app"},
    )

    assert "extends: subject_matter_expert" in cairn.files["schema.yaml"]
    assert "# Node Guide: src.app" in cairn.files["summary.md"]


@pytest.mark.asyncio
async def test_ensure_subject_matter_expert_workspace_preserves_existing_files() -> None:
    class _FakeCairnExternals:
        def __init__(self) -> None:
            self.files: dict[str, str] = {
                "schema.yaml": "version: \"1\"\nname: custom\n",
                "summary.md": "# custom summary\n",
            }

        async def read_file(self, path: str) -> str:
            return self.files.get(path, "")

        async def write_file(self, path: str, content: str) -> None:
            self.files[path] = content

    cairn = _FakeCairnExternals()
    await _ensure_subject_matter_expert_workspace(
        cairn,
        agent_id="agent-app",
        node_attrs={"id": "module:src/app.py", "full_name": "src.app"},
    )

    assert cairn.files["schema.yaml"] == "version: \"1\"\nname: custom\n"
    assert cairn.files["summary.md"] == "# custom summary\n"


@pytest.mark.asyncio
async def test_append_correction_notes_writes_notes_and_summary() -> None:
    class _FakeCairnExternals:
        def __init__(self) -> None:
            self.files: dict[str, str] = {
                "notes.md": "existing note\n",
                "summary.md": "# Node Guide: src.app\n\n## User corrections\n",
            }

        async def read_file(self, path: str) -> str:
            return self.files.get(path, "")

        async def write_file(self, path: str, content: str) -> None:
            self.files[path] = content

    cairn = _FakeCairnExternals()
    await _append_correction_notes(
        cairn,
        request_id="req-2",
        question="What should this return?",
        response="Return a cached value.",
    )

    assert "Correction `req-2`: Return a cached value." in cairn.files["notes.md"]
    assert "`req-2`: Return a cached value." in cairn.files["summary.md"]


def test_extract_human_response_fields_from_activation_event() -> None:
    event = SimpleNamespace(
        event_type="HumanInputResponseEvent",
        payload={
            "request_id": "req-3",
            "question": "Clarify behavior",
            "response": "Use deterministic ordering.",
        },
    )
    request_id, question, response = _extract_human_response_fields(event)
    assert request_id == "req-3"
    assert question == "Clarify behavior"
    assert response == "Use deterministic ordering."
