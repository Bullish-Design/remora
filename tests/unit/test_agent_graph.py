from dataclasses import dataclass
from pathlib import Path
from typing import cast


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


@dataclass(frozen=True)
class FakeNode:
    node_id: str
    name: str
    node_type: str
    file_path: Path
    start_line: int = 0


from remora.config import BundleMetadata
from remora.discovery import CSTNode
from remora.graph import build_graph


def test_build_graph_selects_highest_priority_bundle(tmp_path: Path) -> None:
    lint_path = tmp_path / "agents" / "lint" / "bundle.yaml"
    docstring_path = tmp_path / "agents" / "docstring" / "bundle.yaml"
    _ensure_file(lint_path)
    _ensure_file(docstring_path)

    metadata = {
        "lint": BundleMetadata(
            bundle_name="lint",
            path=lint_path,
            node_types=("function",),
            priority=10,
            requires_context=True,
        ),
        "docstring": BundleMetadata(
            bundle_name="docstring",
            path=docstring_path,
            node_types=("function",),
            priority=20,
            requires_context=True,
        ),
    }

    node = FakeNode(
        node_id="node-1",
        name="foo",
        node_type="function",
        file_path=tmp_path / "src" / "main.py",
        start_line=1,
    )

    graph = build_graph([cast(CSTNode, node)], metadata)

    assert len(graph) == 1
    assert graph[0].bundle_path == docstring_path


def test_build_graph_ignores_unknown_node_type(tmp_path: Path) -> None:
    metadata = {
        "lint": BundleMetadata(
            bundle_name="lint",
            path=tmp_path / "unused" / "bundle.yaml",
            node_types=("function",),
            priority=1,
            requires_context=False,
        )
    }

    node = FakeNode(
        node_id="node-2",
        name="bar",
        node_type="class",
        file_path=tmp_path / "src" / "main.py",
    )

    graph = build_graph([cast(CSTNode, node)], metadata)

    assert graph == []


def test_build_graph_tiebreaks_on_bundle_name(tmp_path: Path) -> None:
    a_path = tmp_path / "agents" / "alpha" / "bundle.yaml"
    z_path = tmp_path / "agents" / "zeta" / "bundle.yaml"
    _ensure_file(a_path)
    _ensure_file(z_path)

    metadata = {
        "zeta": BundleMetadata(
            bundle_name="zeta",
            path=z_path,
            node_types=("helper",),
            priority=5,
            requires_context=False,
        ),
        "alpha": BundleMetadata(
            bundle_name="alpha",
            path=a_path,
            node_types=("helper",),
            priority=5,
            requires_context=False,
        ),
    }

    node = FakeNode(
        node_id="node-3",
        name="helper",
        node_type="helper",
        file_path=tmp_path / "src" / "helper.py",
    )

    graph = build_graph([cast(CSTNode, node)], metadata)

    assert len(graph) == 1
    assert graph[0].bundle_path == a_path
