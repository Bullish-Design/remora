from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from remora.bootstrap.schema_loader import (
    DEFAULT_SCHEMA_YAML,
    TurnSchema,
    _load_yaml,
    load_schema,
    resolve_context_vars,
)


@pytest.mark.asyncio
async def test_default_schema_loaded_when_workspace_schema_missing() -> None:
    cairn = AsyncMock()
    cairn.read_file.return_value = ""

    schema = await load_schema(cairn)

    assert schema.name == "bootstrap_default"
    assert schema.termination == "DONE"
    assert "read_file" in schema.tools


@pytest.mark.asyncio
async def test_workspace_schema_loaded_when_present() -> None:
    cairn = AsyncMock()
    cairn.read_file.return_value = """
version: "1"
name: test_agent
system: "You are test."
tools: [read_file]
max_turns: 3
termination: "DONE"
"""

    schema = await load_schema(cairn)

    assert schema.name == "test_agent"
    assert schema.max_turns == 3
    assert schema.tools == ["read_file"]


@pytest.mark.asyncio
async def test_default_schema_loaded_from_filesystem_when_available(tmp_path: Path) -> None:
    (tmp_path / "DEFAULT_SCHEMA.yaml").write_text(
        """
version: "1"
name: filesystem_default
system: "from file"
tools: [read_file]
max_turns: 2
termination: "DONE"
""".strip(),
        encoding="utf-8",
    )
    cairn = AsyncMock()
    cairn.read_file.return_value = ""

    schema = await load_schema(cairn, system_agents_dir=tmp_path)

    assert schema.name == "filesystem_default"
    assert schema.max_turns == 2


@pytest.mark.asyncio
async def test_extends_merges_base_schema(tmp_path: Path) -> None:
    base = tmp_path / "base_code_agent.yaml"
    base.write_text(
        """
version: "1"
name: base
system: "base system"
context:
  - name: base_ctx
    tool: read_file
tools:
  - read_file
  - graph_find_nodes
max_turns: 4
termination: "DONE"
""".strip(),
        encoding="utf-8",
    )

    cairn = AsyncMock()
    cairn.read_file.return_value = """
extends: base_code_agent
name: child
tools:
  - graph_add_edge
context:
  - name: child_ctx
    tool: graph_node
termination: "DONE"
"""

    schema = await load_schema(cairn, system_agents_dir=tmp_path)

    assert schema.name == "child"
    assert schema.max_turns == 4
    assert schema.tools == ["read_file", "graph_find_nodes", "graph_add_edge"]
    assert [step.name for step in schema.context] == ["base_ctx", "child_ctx"]


def test_resolve_context_vars_replaces_double_brace_tokens() -> None:
    text = "Node {{node}} has {{count}} tasks."
    result = resolve_context_vars(text, {"node": "file:app.py", "count": "3"})

    assert result == "Node file:app.py has 3 tasks."


def test_default_schema_yaml_matches_file() -> None:
    agents_dir = Path("bootstrap/agents")
    default_file = agents_dir / "DEFAULT_SCHEMA.yaml"
    assert default_file.exists()

    from_constant = TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))
    from_file = TurnSchema.model_validate(
        _load_yaml(default_file.read_text(encoding="utf-8"))
    )
    assert from_constant == from_file
