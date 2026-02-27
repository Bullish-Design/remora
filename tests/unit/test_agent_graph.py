from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from remora.core.discovery import CSTNode
from remora.core.graph import build_graph


def _ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


@dataclass(frozen=True)
class FakeNode:
    node_id: str
    name: str
    node_type: str
    file_path: str
    full_name: str
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int


def test_build_graph_maps_node_type(tmp_path: Path) -> None:
    lint_path = tmp_path / "agents" / "lint" / "bundle.yaml"
    _ensure_file(lint_path)

    bundle_mapping = {"function": lint_path}

    node = FakeNode(
        node_id="node-1",
        name="foo",
        node_type="function",
        file_path=str(tmp_path / "src" / "main.py"),
        full_name="function:foo",
        text="def foo(): pass",
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=14,
    )

    graph = build_graph([cast(CSTNode, node)], bundle_mapping)

    assert len(graph) == 1
    assert graph[0].bundle_path == lint_path


def test_build_graph_skips_unknown_node_type(tmp_path: Path) -> None:
    lint_path = tmp_path / "agents" / "lint" / "bundle.yaml"
    _ensure_file(lint_path)

    bundle_mapping = {"function": lint_path}

    node = FakeNode(
        node_id="node-2",
        name="bar",
        node_type="class",
        file_path=str(tmp_path / "src" / "main.py"),
        full_name="class:bar",
        text="class bar: pass",
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=17,
    )

    graph = build_graph([cast(CSTNode, node)], bundle_mapping)

    assert graph == []


def test_build_graph_priority_sorting(tmp_path: Path) -> None:
    file_path = tmp_path / "agents" / "file" / "bundle.yaml"
    section_path = tmp_path / "agents" / "section" / "bundle.yaml"
    _ensure_file(file_path)
    _ensure_file(section_path)

    bundle_mapping = {"file": file_path, "section": section_path}
    priority_mapping = {"section": 10, "file": 1}

    nodes = [
        FakeNode(
            node_id="node-1",
            name="main.py",
            node_type="file",
            file_path=str(tmp_path / "src" / "main.py"),
            full_name="main.py",
            text="print('hi')",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=12,
        ),
        FakeNode(
            node_id="node-2",
            name="Intro",
            node_type="section",
            file_path=str(tmp_path / "README.md"),
            full_name="section:Intro",
            text="# Intro",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=7,
        ),
    ]

    graph = build_graph([cast(CSTNode, node) for node in nodes], bundle_mapping, priority_mapping)

    assert len(graph) == 2
    assert graph[0].id == "node-2"
