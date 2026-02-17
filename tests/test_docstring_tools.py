from __future__ import annotations

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _load_module(path: Path, name: str):
    loader = SourceFileLoader(name, str(path))
    spec = spec_from_file_location(name, path, loader=loader)
    assert spec is not None
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_sample_file(workspace: Path, content: str) -> Path:
    target = workspace / "sample.py"
    target.write_text(content, encoding="utf-8")
    return target


def test_read_current_docstring_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/tools/read_current_docstring.pym",
        "read_current_docstring",
    )
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        'def add(a, b):\n    """Adds numbers."""\n    return a + b\n',
    )

    result = module.run({})

    assert result["docstring"] == "Adds numbers."
    assert result["has_docstring"] is True


def test_read_current_docstring_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/tools/read_current_docstring.pym",
        "read_current_docstring_none",
    )
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def add(a, b):\n    return a + b\n",
    )

    result = module.run({})

    assert result["docstring"] is None
    assert result["has_docstring"] is False


def test_read_type_hints_with_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/tools/read_type_hints.pym",
        "read_type_hints",
    )
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def total(price: float, quantity: int) -> float:\n    return price * quantity\n",
    )

    result = module.run({})

    assert result["parameters"] == [
        {"name": "price", "annotation": "float"},
        {"name": "quantity", "annotation": "int"},
    ]
    assert result["return_annotation"] == "float"
    assert result["has_annotations"] is True


def test_read_type_hints_without_annotations(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/tools/read_type_hints.pym",
        "read_type_hints_none",
    )
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def greet(name):\n    return f'Hi {name}'\n",
    )

    result = module.run({})

    assert result["parameters"] == []
    assert result["return_annotation"] is None
    assert result["has_annotations"] is False


def test_write_docstring_inserts_after_definition(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/tools/write_docstring.pym",
        "write_docstring",
    )
    _write_sample_file(tmp_path, "def add(a, b):\n    return a + b\n")
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def add(a, b):\n    return a + b\n",
    )

    result = module.run({"docstring": "Adds numbers.", "style": "google"})

    updated = (tmp_path / "sample.py").read_text(encoding="utf-8")
    assert result["success"] is True
    assert '"""Adds numbers."""' in updated.splitlines()[1]


def test_write_docstring_replaces_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/tools/write_docstring.pym",
        "write_docstring_replace",
    )
    _write_sample_file(
        tmp_path,
        'def add(a, b):\n    """Old docstring."""\n    return a + b\n',
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        'def add(a, b):\n    """Old docstring."""\n    return a + b\n',
    )

    result = module.run({"docstring": "New docstring.", "style": "google"})

    updated = (tmp_path / "sample.py").read_text(encoding="utf-8")
    assert result["success"] is True
    assert result["replaced_existing"] is True
    assert "Old docstring." not in updated
    assert "New docstring." in updated
    assert updated.count('"""') == 2


def test_docstring_style_defaults_to_google(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/docstring/context/docstring_style.pym",
        "docstring_style",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    assert module.run() == "google"
