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


def _write_sample_module(workspace: Path) -> Path:
    target = workspace / "sample.py"
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return target


def test_analyze_signature_with_types(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/analyze_signature.pym", "analyze_signature")
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def add(a: int, b: int = 1) -> int:\n    return a + b\n",
    )

    result = module.run({})

    assert result["function_name"] == "add"
    assert result["return_type"] == "int"
    assert result["parameters"][0] == {"name": "a", "type": "int", "default": None}
    assert result["parameters"][1] == {"name": "b", "type": "int", "default": 1}
    assert result["is_async"] is False


def test_analyze_signature_without_types(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/analyze_signature.pym", "analyze_signature_no_types")
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def greet(name=\"World\"):\n    return f'Hi {name}'\n",
    )

    result = module.run({})

    assert result["function_name"] == "greet"
    assert result["parameters"][0] == {"name": "name", "type": None, "default": "World"}
    assert result["return_type"] is None


def test_read_existing_tests_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/read_existing_tests.pym", "read_existing_tests")
    _write_sample_module(tmp_path)
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")

    result = module.run({})

    assert result["content"] == ""
    assert result["path"] is None


def test_write_test_file_creates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/write_test_file.pym", "write_test_file")
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    result = module.run({"content": "import sample\n", "path": "tests/test_sample.py"})

    assert result["success"] is True
    assert (tmp_path / "tests" / "test_sample.py").exists()


def test_pytest_config_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/test/context/pytest_config.pym", "pytest_config")
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    assert module.run() == ""


def test_run_tests_passing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/run_tests.pym", "run_tests")
    _write_sample_module(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_sample.py"
    test_file.write_text(
        "import sample\n\n\ndef test_add():\n    assert sample.add(1, 2) == 3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")

    result = module.run({"path": "tests/test_sample.py"})

    assert result["failed"] == 0
    assert result["errors"] == 0
    assert result["passed"] >= 1


def test_run_tests_failing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/run_tests.pym", "run_tests_fail")
    _write_sample_module(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_sample.py"
    test_file.write_text(
        "import sample\n\n\ndef test_add():\n    assert sample.add(1, 2) == 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")

    result = module.run({"path": "tests/test_sample.py"})

    assert result["failed"] >= 1
    assert result["failures"]


def test_submit_builds_agent_result(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(_repo_root() / "agents/test/tools/submit.pym", "submit_test")
    monkeypatch.setenv("REMORA_WORKSPACE_ID", "test-123")

    result = module.run(
        {
            "summary": "Added tests",
            "tests_generated": 2,
            "tests_passing": 2,
            "changed_files": ["tests/test_sample.py"],
        }
    )

    assert result["status"] == "success"
    assert result["workspace_id"] == "test-123"
    assert result["details"]["tests_generated"] == 2
