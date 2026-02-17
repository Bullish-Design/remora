from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from remora.discovery import CSTNode
from remora.errors import AGENT_001
from remora.subagent import SubagentError, load_subagent_definition


def _write_subagent_yaml(agents_dir: Path, *, include_submit: bool = True) -> Path:
    subagent_dir = agents_dir / "lint"
    tools_dir = subagent_dir / "tools"
    context_dir = subagent_dir / "context"
    tools_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)

    run_tool_path = tools_dir / "run_tool.pym"
    submit_path = tools_dir / "submit.pym"
    context_path = context_dir / "config.pym"

    run_tool_path.write_text("", encoding="utf-8")
    submit_path.write_text("", encoding="utf-8")
    context_path.write_text("", encoding="utf-8")

    tools = [
        {
            "name": "run_tool",
            "pym": "lint/tools/run_tool.pym",
            "description": "Run the lint tool.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"path": {"type": "string"}},
            },
            "context_providers": ["lint/context/config.pym"],
        }
    ]
    if include_submit:
        tools.append(
            {
                "name": "submit_result",
                "pym": "lint/tools/submit.pym",
                "description": "Submit the result.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
            }
        )

    subagent_path = subagent_dir / "lint_subagent.yaml"
    subagent_path.write_text(
        yaml.safe_dump(
            {
                "name": "lint_agent",
                "model_id": "ollama/functiongemma-4b-it",
                "max_turns": 12,
                "initial_context": {
                    "system_prompt": "You are a lint agent.",
                    "node_context": "{{ node_name }} {{ node_type }} {{ file_path }} {{ node_text }}",
                },
                "tools": tools,
            }
        ),
        encoding="utf-8",
    )
    return subagent_path


def test_load_subagent_definition_resolves_paths(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    subagent_path = _write_subagent_yaml(agents_dir)
    definition = load_subagent_definition(subagent_path, agents_dir)

    assert definition.name == "lint_agent"
    assert definition.model_id == "ollama/functiongemma-4b-it"
    assert len(definition.tools) == 2
    assert definition.tools_by_name["run_tool"].pym == (agents_dir / "lint/tools/run_tool.pym").resolve()
    assert definition.tools_by_name["run_tool"].context_providers == [
        (agents_dir / "lint/context/config.pym").resolve()
    ]


def test_tool_schemas_are_strict(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    subagent_path = _write_subagent_yaml(agents_dir)
    definition = load_subagent_definition(subagent_path, agents_dir)

    schemas = definition.tool_schemas
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "run_tool"
    assert schemas[0]["function"]["strict"] is True
    assert schemas[0]["function"]["parameters"]["type"] == "object"


def test_missing_submit_result_raises_agent_001(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    subagent_path = _write_subagent_yaml(agents_dir, include_submit=False)

    with pytest.raises(SubagentError) as excinfo:
        load_subagent_definition(subagent_path, agents_dir)

    assert excinfo.value.code == AGENT_001


def test_initial_context_render_interpolates_fields(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    subagent_path = _write_subagent_yaml(agents_dir)
    definition = load_subagent_definition(subagent_path, agents_dir)

    node = CSTNode(
        node_id="node-1",
        node_type="function",
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
    )

    rendered = definition.initial_context.render(node)

    assert "hello function src/example.py" in rendered
    assert "def hello(): ..." in rendered


def test_tools_by_name_lookup_returns_tool(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    subagent_path = _write_subagent_yaml(agents_dir)
    definition = load_subagent_definition(subagent_path, agents_dir)

    tool = definition.tools_by_name["submit_result"]

    assert tool.description == "Submit the result."
