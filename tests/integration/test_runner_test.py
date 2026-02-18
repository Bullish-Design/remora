from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode, NodeType
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
                node_id=f"test_{name}",
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
def test_test_runner_generates_tests(cairn_client_factory) -> None:
    text = _load_fixture()
    node = _function_node(text, "format_currency")
    definition = load_subagent_definition(Path("agents/test/test_subagent.yaml"), agents_dir=Path("agents"))
    definition = definition.model_copy(update={"max_turns": 30})
    cairn_client = cairn_client_factory(node.text)
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="test-test_001",
        cairn_client=cairn_client,
        server_config=_server_config(),
        runner_config=_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.changed_files
    assert any("test_" in path for path in result.changed_files)

    workspace_path = cairn_client.workspace_path("test-test_001")
    test_file_paths = [workspace_path / path for path in result.changed_files if "test_" in path]
    assert test_file_paths
    test_content = test_file_paths[0].read_text(encoding="utf-8")
    ast.parse(test_content)
    assert "integration_target" in test_content
    assert "import" in test_content
