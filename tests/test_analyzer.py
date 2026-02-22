from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.analyzer import RemoraAnalyzer, WorkspaceInfo, WorkspaceState
from remora.config import RemoraConfig
from remora.events import EventName, EventStatus
from remora.results import AgentResult, AgentStatus, AnalysisResults, NodeResult


@pytest.mark.asyncio
async def test_accept_emits_workspace_accepted() -> None:
    config = RemoraConfig()
    emitter = MagicMock()
    analyzer = RemoraAnalyzer(config, event_emitter=emitter)

    result = AgentResult(status=AgentStatus.SUCCESS, workspace_id="ws-1")
    info = WorkspaceInfo(workspace_id="ws-1", node_id="node-1", operation="lint", result=result)
    analyzer._workspaces = {("node-1", "lint"): info}
    analyzer._cairn_merge = AsyncMock()

    await analyzer.accept("node-1", "lint")

    analyzer._cairn_merge.assert_awaited_once_with("ws-1")
    assert info.state == WorkspaceState.ACCEPTED
    payload = emitter.emit.call_args[0][0]
    assert payload["event"] == EventName.WORKSPACE_ACCEPTED
    assert payload["status"] == EventStatus.OK


@pytest.mark.asyncio
async def test_reject_emits_workspace_rejected() -> None:
    config = RemoraConfig()
    emitter = MagicMock()
    analyzer = RemoraAnalyzer(config, event_emitter=emitter)

    result = AgentResult(status=AgentStatus.SUCCESS, workspace_id="ws-2")
    info = WorkspaceInfo(workspace_id="ws-2", node_id="node-2", operation="test", result=result)
    analyzer._workspaces = {("node-2", "test"): info}
    analyzer._cairn_discard = AsyncMock()

    await analyzer.reject("node-2", "test")

    analyzer._cairn_discard.assert_awaited_once_with("ws-2")
    assert info.state == WorkspaceState.REJECTED
    payload = emitter.emit.call_args[0][0]
    assert payload["event"] == EventName.WORKSPACE_REJECTED
    assert payload["status"] == EventStatus.OK


@pytest.mark.asyncio
async def test_retry_replaces_operation_result(monkeypatch) -> None:
    config = RemoraConfig()
    analyzer = RemoraAnalyzer(config)

    node = SimpleNamespace(node_id="node-3", name="hello", file_path=Path("src/example.py"))
    analyzer._nodes = [node]

    initial_result = AgentResult(status=AgentStatus.FAILED, workspace_id="ws-3")
    info = WorkspaceInfo(
        workspace_id="ws-3",
        node_id="node-3",
        operation="lint",
        result=initial_result,
    )
    analyzer._workspaces = {("node-3", "lint"): info}
    analyzer._results = AnalysisResults.from_node_results(
        [NodeResult(node_id="node-3", node_name="hello", file_path=node.file_path, operations={"lint": initial_result})]
    )
    analyzer.reject = AsyncMock()

    replacement = AgentResult(status=AgentStatus.SUCCESS, workspace_id="ws-3")

    class FakeCoordinator:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def process_node(self, _node, operations):
            return NodeResult(
                node_id=_node.node_id,
                node_name=_node.name,
                file_path=_node.file_path,
                operations={operations[0]: replacement},
            )

    analyzer._coordinator_cls = FakeCoordinator

    result = await analyzer.retry("node-3", "lint")

    analyzer.reject.assert_awaited_once_with("node-3", "lint")
    assert result == replacement
    assert info.state == WorkspaceState.PENDING
    assert analyzer._results.nodes[0].operations["lint"] == replacement


@pytest.mark.asyncio
async def test_cairn_merge_refuses_outside_project_root(tmp_path: Path) -> None:
    config = RemoraConfig()
    config.agents_dir = tmp_path / "agents"
    config.agents_dir.mkdir()
    config.cairn.home = tmp_path / "cache"

    analyzer = RemoraAnalyzer(config)
    workspace_id = "lint-node"
    workspace_db = analyzer._workspace_db_path(workspace_id)
    workspace_db.parent.mkdir(parents=True, exist_ok=True)
    workspace_db.write_text("db", encoding="utf-8")

    class FakeOverlay:
        async def list_changes(self, _path: str):
            return ["/../outside.txt"]

        async def reset(self) -> None:
            return None

    class FakeFiles:
        async def read(self, _path: str, mode: str = "binary", encoding=None):
            return b"data"

    class FakeWorkspace:
        overlay = FakeOverlay()
        files = FakeFiles()

    @asynccontextmanager
    async def fake_open_workspace(_path: Path):
        yield FakeWorkspace()

    analyzer._workspace_manager.open_workspace = fake_open_workspace

    with pytest.raises(ValueError):
        await analyzer._cairn_merge(workspace_id)
