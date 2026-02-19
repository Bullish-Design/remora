from __future__ import annotations

import ast
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
                node_id=f"docstring_{name}",
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


def _assert_docstring(module: ast.Module, name: str) -> None:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            assert ast.get_docstring(node)
            return
    raise AssertionError(f"Function {name} not found")


@pytest.mark.integration
def test_docstring_runner_adds_docstrings(grail_executor_factory, tmp_path) -> None:
    text = _load_fixture()
    first_node = _function_node(text, "format_currency")
    second_node = _function_node(text, "parse_config")
    definition = load_subagent_definition(Path("agents/docstring/docstring_subagent.yaml"), agents_dir=Path("agents"))
    definition = definition.model_copy(update={"max_turns": 30})
    definition = definition.model_copy(update={"max_turns": 30})
    
    executor = grail_executor_factory()
    workspace_dir = tmp_path / "docstring-docstring_001"
    executor.setup_workspace(workspace_dir, node_text=first_node.text)

    runner = FunctionGemmaRunner(
        definition=definition,
        node=first_node,
        ctx=RemoraAgentContext(agent_id="docstring-docstring_001", task="docstring", operation="docstring", node_id="docstring_format_currency"),
        grail_executor=executor,
        grail_dir=workspace_dir,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )
    result = asyncio.run(runner.run())
    assert result.status == "success"
    assert result.changed_files

    executor.setup_workspace(workspace_dir, node_text=second_node.text)
    runner = FunctionGemmaRunner(
        definition=definition,
        node=second_node,
        ctx=RemoraAgentContext(agent_id="docstring-docstring_001", task="docstring", operation="docstring", node_id="docstring_parse_config"),
        grail_executor=executor,
        grail_dir=workspace_dir,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )
    result = asyncio.run(runner.run())
    assert result.status == "success"

    workspace_path = workspace_dir
    updated = (workspace_path / "tests/fixtures/integration_target.py").read_text(encoding="utf-8")
    module = ast.parse(updated)
    _assert_docstring(module, "format_currency")
    _assert_docstring(module, "parse_config")
