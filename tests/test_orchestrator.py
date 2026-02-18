from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from remora.config import OperationConfig, RemoraConfig, RunnerConfig
from remora.discovery import CSTNode
from remora.errors import AGENT_001
from remora.orchestrator import Coordinator
from remora.results import AgentResult
from remora.subagent import SubagentError


class FakeCairnClient:
    async def run_pym(self, path: object, workspace_id: str, inputs: dict[str, object]) -> dict[str, object]:
        return {}


def _make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type="function",
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
    )


def _make_config(tmp_path: Path, operations: dict[str, OperationConfig], *, max_concurrent: int = 4) -> RemoraConfig:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return RemoraConfig(
        agents_dir=agents_dir,
        operations=operations,
        runner=RunnerConfig(max_concurrent_runners=max_concurrent),
    )


def test_process_node_returns_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    operations = {
        "lint": OperationConfig(subagent="lint/lint_subagent.yaml"),
        "test": OperationConfig(subagent="test/test_subagent.yaml"),
        "docstring": OperationConfig(subagent="docstring/docstring_subagent.yaml"),
    }
    config = _make_config(tmp_path, operations, max_concurrent=3)
    node = _make_node()

    results_map = {
        "lint": AgentResult(status="success", workspace_id="lint-node-1", summary="lint", changed_files=[]),
        "test": AgentResult(status="success", workspace_id="test-node-1", summary="test", changed_files=[]),
        "docstring": AgentResult(status="success", workspace_id="docstring-node-1", summary="doc", changed_files=[]),
    }

    def fake_load_subagent_definition(path: Path, agents_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(name=path.stem)

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            workspace_id: str,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = workspace_id

        async def run(self) -> AgentResult:
            operation = self.workspace_id.split("-", 1)[0]
            return results_map[operation]

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    coordinator = Coordinator(config, FakeCairnClient())
    result = asyncio.run(coordinator.process_node(node, ["lint", "test", "docstring"]))

    assert result.operations["lint"].summary == "lint"
    assert result.operations["test"].summary == "test"
    assert result.operations["docstring"].summary == "doc"
    assert result.errors == []


def test_process_node_respects_semaphore(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    operations = {
        "lint": OperationConfig(subagent="lint/lint_subagent.yaml"),
        "test": OperationConfig(subagent="test/test_subagent.yaml"),
        "docstring": OperationConfig(subagent="docstring/docstring_subagent.yaml"),
        "sample": OperationConfig(subagent="sample/sample_subagent.yaml"),
    }
    config = _make_config(tmp_path, operations, max_concurrent=2)
    node = _make_node()
    state = {"current": 0, "max": 0}

    def fake_load_subagent_definition(path: Path, agents_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(name=path.stem)

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            workspace_id: str,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = workspace_id

        async def run(self) -> AgentResult:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
            await asyncio.sleep(0.02)
            state["current"] -= 1
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok", changed_files=[])

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    coordinator = Coordinator(config, FakeCairnClient())
    asyncio.run(coordinator.process_node(node, ["lint", "test", "docstring", "sample"]))

    assert state["max"] == 2


def test_process_node_captures_runner_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    operations = {
        "lint": OperationConfig(subagent="lint/lint_subagent.yaml"),
        "test": OperationConfig(subagent="test/test_subagent.yaml"),
        "docstring": OperationConfig(subagent="docstring/docstring_subagent.yaml"),
    }
    config = _make_config(tmp_path, operations)
    node = _make_node()

    results_map: dict[str, AgentResult | Exception] = {
        "lint": AgentResult(status="success", workspace_id="lint-node-1", summary="lint", changed_files=[]),
        "test": RuntimeError("boom"),
        "docstring": AgentResult(status="success", workspace_id="docstring-node-1", summary="doc", changed_files=[]),
    }

    def fake_load_subagent_definition(path: Path, agents_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(name=path.stem)

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            workspace_id: str,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = workspace_id

        async def run(self) -> AgentResult:
            operation = self.workspace_id.split("-", 1)[0]
            result = results_map[operation]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    coordinator = Coordinator(config, FakeCairnClient())
    result = asyncio.run(coordinator.process_node(node, ["lint", "test", "docstring"]))

    assert "test" not in result.operations
    assert any(error["operation"] == "test" and error["phase"] == "run" for error in result.errors)
    assert result.operations["lint"].summary == "lint"
    assert result.operations["docstring"].summary == "doc"


def test_process_node_skips_disabled_operation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    operations = {
        "lint": OperationConfig(subagent="lint/lint_subagent.yaml"),
        "test": OperationConfig(subagent="test/test_subagent.yaml", enabled=False),
    }
    config = _make_config(tmp_path, operations)
    node = _make_node()
    called: list[str] = []

    def fake_load_subagent_definition(path: Path, agents_dir: Path) -> SimpleNamespace:
        called.append(path.stem)
        return SimpleNamespace(name=path.stem)

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            workspace_id: str,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = workspace_id

        async def run(self) -> AgentResult:
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok", changed_files=[])

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    coordinator = Coordinator(config, FakeCairnClient())
    result = asyncio.run(coordinator.process_node(node, ["lint", "test"]))

    assert called == ["lint_subagent"]
    assert "test" not in result.operations
    assert "lint" in result.operations


def test_bad_subagent_path_records_init_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    operations = {
        "good": OperationConfig(subagent="good/good_subagent.yaml"),
        "bad": OperationConfig(subagent="bad/missing.yaml"),
    }
    config = _make_config(tmp_path, operations)
    node = _make_node()

    def fake_load_subagent_definition(path: Path, agents_dir: Path) -> SimpleNamespace:
        if "missing" in str(path):
            raise SubagentError(AGENT_001, f"Failed to read subagent definition: {path}")
        return SimpleNamespace(name=path.stem)

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            workspace_id: str,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = workspace_id

        async def run(self) -> AgentResult:
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok", changed_files=[])

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    coordinator = Coordinator(config, FakeCairnClient())
    result = asyncio.run(coordinator.process_node(node, ["good", "bad"]))

    assert "good" in result.operations
    assert "bad" not in result.operations
    assert any(error["operation"] == "bad" and error["phase"] == "init" for error in result.errors)
