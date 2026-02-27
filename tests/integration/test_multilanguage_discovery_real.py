from __future__ import annotations

from collections import defaultdict
from importlib import resources
from pathlib import Path

import pytest

from remora.core.discovery import CSTNode, discover


pytestmark = pytest.mark.integration


@pytest.fixture
def fixture_root() -> Path:
    fixture = resources.files("remora") / "fixtures" / "multilang_project"
    with resources.as_file(fixture) as path:
        yield path


def _group_by_path(nodes: list[CSTNode]) -> dict[Path, list[CSTNode]]:
    grouped: dict[Path, list[CSTNode]] = defaultdict(list)
    for node in nodes:
        grouped[Path(node.file_path)].append(node)
    return grouped


def _names(nodes: list[CSTNode], node_type: str) -> set[str]:
    return {node.name for node in nodes if node.node_type == node_type}


def test_multilanguage_project_discovery(fixture_root: Path) -> None:
    nodes = discover([fixture_root])
    grouped = _group_by_path(nodes)

    py_path = fixture_root / "app.py"
    md_path = fixture_root / "README.md"
    toml_path = fixture_root / "config" / "settings.toml"

    assert py_path in grouped
    assert md_path in grouped
    assert toml_path in grouped

    py_nodes = grouped[py_path]
    assert "Client" in _names(py_nodes, "class")
    assert "load_settings" in _names(py_nodes, "function")
    assert {"__init__", "ping"}.issubset(_names(py_nodes, "method"))

    md_nodes = grouped[md_path]
    assert {
        "Remora Multi-Language Demo",
        "Usage",
        "Configuration",
    }.issubset(_names(md_nodes, "section"))
    assert "python" in _names(md_nodes, "code_block")

    toml_nodes = grouped[toml_path]
    assert "project" in _names(toml_nodes, "table")
    assert "tool.pytest.ini_options" in _names(toml_nodes, "table")
    assert "tool.hatch.build.targets" in _names(toml_nodes, "array_table")


def test_multilanguage_discovery_filtering(fixture_root: Path) -> None:
    nodes = discover([fixture_root], languages=["markdown", "toml"])
    grouped = _group_by_path(nodes)

    py_path = fixture_root / "app.py"
    md_path = fixture_root / "README.md"
    toml_path = fixture_root / "config" / "settings.toml"

    assert py_path not in grouped
    assert md_path in grouped
    assert toml_path in grouped
