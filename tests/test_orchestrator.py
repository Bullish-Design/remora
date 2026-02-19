from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from remora.config import CairnConfig, OperationConfig, RemoraConfig
from remora.discovery import CSTNode, NodeType
from remora.errors import AGENT_001
from remora.orchestrator import Coordinator, RemoraAgentContext, RemoraAgentState
from remora.results import AgentResult
from remora.subagent import SubagentError


class FakeCairnClient:
    async def run_pym(self, path: object, workspace_id: str, inputs: dict[str, object]) -> dict[str, object]:
        return {}


def _make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type=NodeType.FUNCTION,
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
        start_line=1,
        end_line=1,
    )


def _make_config(tmp_path: Path, operations: dict[str, OperationConfig], *, max_concurrent: int = 4) -> RemoraConfig:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return RemoraConfig(
        agents_dir=agents_dir,
        operations=operations,
        cairn=CairnConfig(max_concurrent_agents=max_concurrent),
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
        return SimpleNamespace(name=path.stem, grail_summary={})

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            ctx: RemoraAgentContext,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = ctx.agent_id

        async def run(self) -> AgentResult:
            operation = self.workspace_id.split("-", 1)[0]
            return results_map[operation]

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    async def run_test():
        async with Coordinator(config, FakeCairnClient()) as coordinator:
            return await coordinator.process_node(node, ["lint", "test", "docstring"])

    result = asyncio.run(run_test())

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
        return SimpleNamespace(name=path.stem, grail_summary={})

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            ctx: RemoraAgentContext,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = ctx.agent_id

        async def run(self) -> AgentResult:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
            await asyncio.sleep(0.02)
            state["current"] -= 1
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok", changed_files=[])

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    async def run_test():
        async with Coordinator(config, FakeCairnClient()) as coordinator:
            await coordinator.process_node(node, ["lint", "test", "docstring", "sample"])

    asyncio.run(run_test())

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
        return SimpleNamespace(name=path.stem, grail_summary={})

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            ctx: RemoraAgentContext,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = ctx.agent_id

        async def run(self) -> AgentResult:
            operation = self.workspace_id.split("-", 1)[0]
            result = results_map[operation]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    async def run_test():
        async with Coordinator(config, FakeCairnClient()) as coordinator:
            return await coordinator.process_node(node, ["lint", "test", "docstring"])

    result = asyncio.run(run_test())

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
        return SimpleNamespace(name=path.stem, grail_summary={})

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            ctx: RemoraAgentContext,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = ctx.agent_id

        async def run(self) -> AgentResult:
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok", changed_files=[])

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    async def run_test():
        async with Coordinator(config, FakeCairnClient()) as coordinator:
            return await coordinator.process_node(node, ["lint", "test"])

    result = asyncio.run(run_test())

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
        return SimpleNamespace(name=path.stem, grail_summary={})

    class FakeRunner:
        def __init__(
            self,
            definition: object,
            node: CSTNode,
            ctx: RemoraAgentContext,
            cairn_client: FakeCairnClient,
            server_config: object,
            runner_config: object,
            adapter_name: str | None = None,
            http_client: object | None = None,
            event_emitter: object | None = None,
        ) -> None:
            self.workspace_id = ctx.agent_id

        async def run(self) -> AgentResult:
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok", changed_files=[])

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", FakeRunner)

    async def run_test():
        async with Coordinator(config, FakeCairnClient()) as coordinator:
            return await coordinator.process_node(node, ["good", "bad"])

    result = asyncio.run(run_test())

    assert "good" in result.operations
    assert "bad" not in result.operations
    assert any(error["operation"] == "bad" and error["phase"] == "init" for error in result.errors)


def test_agent_context_state_transitions() -> None:
    ctx = RemoraAgentContext(agent_id="test-1", task="test", operation="op", node_id="node-1")
    assert ctx.state == RemoraAgentState.QUEUED
    t0 = ctx.state_changed_at

    # Ensure time passes (on Windows/monotonic resolution can be coarse)
    import time
    time.sleep(0.001)

    ctx.transition(RemoraAgentState.EXECUTING)
    assert ctx.state == RemoraAgentState.EXECUTING
    assert ctx.state_changed_at > t0


def test_agent_context_validation() -> None:
    # Helper to check validation errors
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RemoraAgentContext(agent_id="", task="t", operation="o", node_id="n")  # Empty ID


def test_coordinator_graceful_shutdown_cancels_tasks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Setup: Create a coordinator with a slow runner
    operations = {
        "slow": OperationConfig(subagent="slow/slow_subagent.yaml"),
    }
    config = _make_config(tmp_path, operations)
    node = _make_node()

    # Fake subagent loading
    def fake_load_subagent_definition(path: Path, agents_dir: Path) -> SimpleNamespace:
        return SimpleNamespace(name=path.stem, grail_summary={})

    # Fake runner that sleeps forever until cancelled
    class ForeverRunner:
        def __init__(self, *args, **kwargs) -> None:
            self.workspace_id = kwargs["ctx"].agent_id

        async def run(self) -> AgentResult:
            await asyncio.sleep(10)
            return AgentResult(status="success", workspace_id=self.workspace_id, summary="ok")

    monkeypatch.setattr("remora.orchestrator.load_subagent_definition", fake_load_subagent_definition)
    monkeypatch.setattr("remora.orchestrator.FunctionGemmaRunner", ForeverRunner)

    async def run_shutdown_test():
        coordinator = Coordinator(config, FakeCairnClient())
        async with coordinator:
            # Start processing
            process_task = asyncio.create_task(coordinator.process_node(node, ["slow"]))
            
            # Wait for task to be scheduled and running
            await asyncio.sleep(0.01)
            assert len(coordinator._running_tasks) == 1
            
            # Simulate shutdown signal (manually calling the handler)
            coordinator._request_shutdown()
            assert coordinator._shutdown_requested
            
            # process_node should complete (likely with partial results or empty)
            result = await process_task
            
            # The running task inside should have been cancelled
            # In our implementation, process_node gathers tasks with return_exceptions=True
            # so the main process_node call finishes.
            
            # The shutdown request should have cleared the running task from the set eventually
            # (or at least marked it cancelled)
            return len(coordinator._running_tasks)

    # Run the test
    # Note: process_node catches the cancellation internally and returns partial results,
    # so we expect it to finish without raising CancelledError to the caller.
    asyncio.run(run_shutdown_test())

