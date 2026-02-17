from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from remora.discovery import CSTNode
from remora.runner import FunctionGemmaRunner
from remora.subagent import load_subagent_definition

FIXTURE = Path("tests/fixtures/integration_target.py")


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
                node_type="function",
                name=name,
                file_path=FIXTURE,
                start_byte=start_byte,
                end_byte=end_byte,
                text=snippet,
            )
    raise AssertionError(f"Function {name} not found")


def _assert_docstring(module: ast.Module, name: str) -> None:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            assert ast.get_docstring(node)
            return
    raise AssertionError(f"Function {name} not found")


@pytest.mark.integration
def test_docstring_runner_adds_docstrings(cairn_client_factory) -> None:
    text = _load_fixture()
    first_node = _function_node(text, "format_currency")
    second_node = _function_node(text, "parse_config")
    definition = load_subagent_definition(Path("agents/docstring/docstring_subagent.yaml"), agents_dir=Path("agents"))
    definition = definition.model_copy(update={"max_turns": 30})
    cairn_client = cairn_client_factory(first_node.text)

    runner = FunctionGemmaRunner(
        definition=definition,
        node=first_node,
        workspace_id="docstring-docstring_001",
        cairn_client=cairn_client,
    )
    result = asyncio.run(runner.run())
    assert result.status == "success"
    assert result.changed_files

    cairn_client.node_text = second_node.text
    runner = FunctionGemmaRunner(
        definition=definition,
        node=second_node,
        workspace_id="docstring-docstring_001",
        cairn_client=cairn_client,
    )
    result = asyncio.run(runner.run())
    assert result.status == "success"

    workspace_path = cairn_client.workspace_path("docstring-docstring_001")
    updated = (workspace_path / "tests/fixtures/integration_target.py").read_text(encoding="utf-8")
    module = ast.parse(updated)
    _assert_docstring(module, "format_currency")
    _assert_docstring(module, "parse_config")
