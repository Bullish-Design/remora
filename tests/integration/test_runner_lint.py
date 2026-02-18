from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode
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
def test_lint_runner_fixes_issues(cairn_client_factory) -> None:
    text = _load_fixture()
    node = CSTNode(
        node_id="lint_001",
        node_type="file",
        name="integration_target",
        file_path=FIXTURE,
        start_byte=0,
        end_byte=len(text.encode()),
        text=text,
    )
    definition = load_subagent_definition(Path("agents/lint/lint_subagent.yaml"), agents_dir=Path("agents"))
    definition = definition.model_copy(update={"max_turns": 30})
    cairn_client = cairn_client_factory(text)
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="lint-lint_001",
        cairn_client=cairn_client,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.changed_files
    assert result.details.get("issues_fixed", 0) >= 1

    workspace_path = cairn_client.workspace_path("lint-lint_001")
    updated = (workspace_path / "tests/fixtures/integration_target.py").read_text(encoding="utf-8")
    assert updated != text
