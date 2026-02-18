from __future__ import annotations

from pathlib import Path

import pytest

from tests.utils.grail_runtime import assert_artifacts, build_file_externals, run_script

pytestmark = pytest.mark.grail_runtime


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path(relative: str) -> Path:
    return _repo_root() / relative


def _write_sample_file(workspace: Path, content: str) -> Path:
    target = workspace / "sample.py"
    target.write_text(content, encoding="utf-8")
    return target


def test_read_current_docstring_returns_text(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/tools/read_current_docstring.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "node_text_input": 'def add(a, b):\n    """Adds numbers."""\n    return a + b\n',
            "target_file_input": None,
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "read_current_docstring")
    assert result["docstring"] == "Adds numbers."
    assert result["has_docstring"] is True


def test_read_current_docstring_returns_none(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/tools/read_current_docstring.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"node_text_input": "def add(a, b):\n    return a + b\n", "target_file_input": None},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "read_current_docstring")
    assert result["docstring"] is None
    assert result["has_docstring"] is False


def test_read_type_hints_with_annotations(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/tools/read_type_hints.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "node_text_input": "def total(price: float, quantity: int) -> float:\n    return price * quantity\n",
            "target_file_input": None,
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "read_type_hints")
    assert result["parameters"] == [
        {"name": "price", "annotation": "float"},
        {"name": "quantity", "annotation": "int"},
    ]
    assert result["return_annotation"] == "float"
    assert result["has_annotations"] is True


def test_read_type_hints_without_annotations(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/tools/read_type_hints.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"node_text_input": "def greet(name):\n    return f'Hi {name}'\n", "target_file_input": None},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "read_type_hints")
    assert result["parameters"] == []
    assert result["return_annotation"] is None
    assert result["has_annotations"] is False


def test_write_docstring_inserts_after_definition(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/tools/write_docstring.pym")
    _write_sample_file(tmp_path, "def add(a, b):\n    return a + b\n")
    externals = build_file_externals(tmp_path)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "docstring": "Adds numbers.",
            "style": "google",
            "node_text_input": "def add(a, b):\n    return a + b\n",
            "target_file_input": "sample.py",
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    updated = (tmp_path / "sample.py").read_text(encoding="utf-8")
    assert_artifacts(grail_dir, "write_docstring")
    assert result["success"] is True
    assert '"""Adds numbers."""' in updated.splitlines()[1]


def test_write_docstring_replaces_existing(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/tools/write_docstring.pym")
    _write_sample_file(
        tmp_path,
        'def add(a, b):\n    """Old docstring."""\n    return a + b\n',
    )
    externals = build_file_externals(tmp_path)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "docstring": "New docstring.",
            "style": "google",
            "node_text_input": 'def add(a, b):\n    """Old docstring."""\n    return a + b\n',
            "target_file_input": "sample.py",
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    updated = (tmp_path / "sample.py").read_text(encoding="utf-8")
    assert_artifacts(grail_dir, "write_docstring")
    assert result["success"] is True
    assert result["replaced_existing"] is True
    assert "Old docstring." not in updated
    assert "New docstring." in updated
    assert updated.count('"""') == 2


def test_docstring_style_defaults_to_google(tmp_path: Path) -> None:
    path = _script_path("agents/docstring/context/docstring_style.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(path=path, inputs={"noop": False}, externals=externals, grail_dir=grail_dir)

    assert_artifacts(grail_dir, "docstring_style")
    assert result == "google"
