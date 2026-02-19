from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode, NodeType
from remora.orchestrator import RemoraAgentContext
from remora.runner import FunctionGemmaRunner
from remora.subagent import load_subagent_definition

FIXTURE = Path("tests/fixtures/integration_target.py")


def _server_config() -> ServerConfig:
    return ServerConfig()


def _runner_config() -> RunnerConfig:
    return RunnerConfig()


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.mark.integration
def test_lint_runner_fixes_issues(grail_executor_factory, tmp_path) -> None:
    text = _load_fixture()
    node = CSTNode(
        node_id="lint_001",
        node_type=NodeType.FILE,
        name="integration_target",
        file_path=FIXTURE,
        start_byte=0,
        end_byte=len(text.encode()),
        text=text,
        start_line=1,
        end_line=text.count("\n") + 1,
    )
    definition = load_subagent_definition(Path("agents/lint/lint_subagent.yaml"), agents_dir=Path("agents"))
    definition = definition.model_copy(update={"max_turns": 30})
    
    executor = grail_executor_factory()
    workspace_dir = tmp_path / "lint-lint_001"
    executor.setup_workspace(workspace_dir, node_text=text)

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=RemoraAgentContext(agent_id="lint-lint_001", task="lint", operation="lint", node_id="lint_001"),
        grail_executor=executor,
        grail_dir=workspace_dir,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )

    result = asyncio.run(runner.run())

    # Result verification
    assert result.status == "success"
    assert result.changed_files
    assert result.details.get("issues_fixed", 0) >= 1

    updated = (workspace_dir / "tests/fixtures/integration_target.py").read_text(encoding="utf-8")
    assert updated != text
