from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from remora.core.discovery import CSTNode, discover


pytestmark = pytest.mark.integration

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "real_world_project"


def _group_by_path(nodes: list[CSTNode]) -> dict[Path, list[CSTNode]]:
    grouped: dict[Path, list[CSTNode]] = defaultdict(list)
    for node in nodes:
        grouped[Path(node.file_path)].append(node)
    return grouped


def _names(nodes: list[CSTNode], node_type: str) -> set[str]:
    return {node.name for node in nodes if node.node_type == node_type}


def _file_node(nodes: list[CSTNode]) -> CSTNode:
    for node in nodes:
        if node.node_type == "file":
            return node
    raise AssertionError("Expected file node not found")


def test_real_world_python_project_discovery() -> None:
    nodes = discover([FIXTURE_ROOT], languages=["python"])
    grouped = _group_by_path(nodes)

    models_path = FIXTURE_ROOT / "src" / "models.py"
    repository_path = FIXTURE_ROOT / "src" / "repository.py"
    services_path = FIXTURE_ROOT / "src" / "services.py"
    utils_path = FIXTURE_ROOT / "src" / "utils.py"

    assert models_path in grouped
    assert repository_path in grouped
    assert services_path in grouped
    assert utils_path in grouped

    model_nodes = grouped[models_path]
    assert {"User", "Admin"}.issubset(_names(model_nodes, "class"))
    assert "can_manage" in _names(model_nodes, "method")

    repository_nodes = grouped[repository_path]
    assert {"BaseRepository", "UserRepository"}.issubset(_names(repository_nodes, "class"))
    assert {"__init__", "save", "get"}.issubset(_names(repository_nodes, "method"))

    services_nodes = grouped[services_path]
    assert "UserService" in _names(services_nodes, "class")
    assert "audit" in _names(services_nodes, "function")
    assert {"get_user", "normalize_name"}.issubset(_names(services_nodes, "function"))

    utils_nodes = grouped[utils_path]
    assert {"parse_int", "format_user", "chunk"}.issubset(_names(utils_nodes, "function"))


def test_large_and_edge_case_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    large_file = project_root / "large_module.py"
    empty_file = project_root / "empty.py"
    broken_file = project_root / "syntax_error.py"

    lines = ["def function_0():", "    return 0", ""]
    lines.extend([f"VALUE_{i} = {i}" for i in range(1, 1195)])
    lines.extend(["", "def function_last():", "    return 1199"])
    large_file.write_text("\n".join(lines), encoding="utf-8")

    empty_file.write_text("", encoding="utf-8")
    broken_file.write_text("def broken(:\n    pass\n", encoding="utf-8")

    nodes = discover([project_root], languages=["python"])
    grouped = _group_by_path(nodes)

    assert large_file in grouped
    assert empty_file in grouped
    assert broken_file in grouped

    large_nodes = grouped[large_file]
    file_node = _file_node(large_nodes)
    assert file_node.end_line == len(lines)
    assert {"function_0", "function_last"}.issubset(_names(large_nodes, "function"))

    empty_nodes = grouped[empty_file]
    assert _file_node(empty_nodes).end_line == 1
    assert not _names(empty_nodes, "function")
    assert not _names(empty_nodes, "class")

    broken_nodes = grouped[broken_file]
    assert _file_node(broken_nodes)
