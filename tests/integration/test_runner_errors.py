from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode, NodeType
from remora.errors import AGENT_002, AGENT_003
from remora.orchestrator import RemoraAgentContext
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import load_subagent_definition

DEFAULT_SERVER_URL = "http://remora-server:8000/v1"
FIXTURE = Path("tests/fixtures/integration_target.py")


def _server_config(base_url: str = DEFAULT_SERVER_URL) -> ServerConfig:
    return ServerConfig(
        base_url=base_url,
        api_key="EMPTY",
        timeout=30,
        default_adapter="google/functiongemma-270m-it",
    )


def _runner_config() -> RunnerConfig:
    return RunnerConfig()


def _load_fixture() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _function_node(text: str, name: str) -> CSTNode:
    module = ast.parse(text)
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            snippet = ast.get_source_segment(text, node)
            if snippet is None:
                raise AssertionError(f"Missing source for {name}")
            start_index = text.index(snippet)
            start_byte = len(text[:start_index].encode())
            end_byte = start_byte + len(snippet.encode())
            return CSTNode(
                node_id=f"errors_{name}",
                node_type=NodeType.FUNCTION,
                name=name,
                file_path=FIXTURE,
                start_byte=start_byte,
                end_byte=end_byte,
                text=snippet,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
            )
    raise AssertionError(f"Function {name} not found")


@pytest.mark.integration
def test_runner_unreachable_server_does_not_block_others(grail_executor_factory, tmp_path) -> None:
    text = _load_fixture()
    node = _function_node(text, "format_currency")
    definition = load_subagent_definition(Path("agents/test/test_subagent.yaml"), agents_dir=Path("agents"))
    
    executor = grail_executor_factory()
    workspace_dir_1 = tmp_path / "error-missing-model"
    executor.setup_workspace(workspace_dir_1, node_text=node.text)

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=RemoraAgentContext(agent_id="error-missing-model", task="test", operation="test", node_id="errors_format_currency"),
        grail_executor=executor,
        grail_dir=workspace_dir_1,
        server_config=_server_config("http://missing-host:8000/v1"),
        runner_config=_runner_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    assert excinfo.value.error_code == AGENT_002

    workspace_dir_2 = tmp_path / "error-valid-model"
    executor.setup_workspace(workspace_dir_2, node_text=node.text)
    
    FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=RemoraAgentContext(agent_id="error-valid-model", task="test", operation="test", node_id="errors_format_currency"),
        grail_executor=executor,
        grail_dir=workspace_dir_2,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )


@pytest.mark.integration
def test_runner_respects_turn_limit(grail_executor_factory, tmp_path) -> None:
    text = _load_fixture()
    node = _function_node(text, "format_currency")
    definition = load_subagent_definition(Path("agents/test/test_subagent.yaml"), agents_dir=Path("agents"))
    definition = definition.model_copy(update={"max_turns": 1})

    executor = grail_executor_factory()
    workspace_dir = tmp_path / "error-turn-limit"
    executor.setup_workspace(workspace_dir, node_text=node.text)

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=RemoraAgentContext(agent_id="error-turn-limit", task="test", operation="test", node_id="errors_format_currency"),
        grail_executor=executor,
        grail_dir=workspace_dir,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    assert excinfo.value.error_code == AGENT_003
