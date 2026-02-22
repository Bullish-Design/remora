from __future__ import annotations

from pathlib import Path

import pytest

from tests.utils.grail_runtime import assert_artifacts, build_file_externals, run_script
from tests.utils.tool_contract import assert_valid_tool_result

pytestmark = pytest.mark.grail_runtime


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path(relative: str) -> Path:
    return _repo_root() / relative


def _write_sample_module(workspace: Path) -> Path:
    target = workspace / "sample.py"
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return target


def _write_report(workspace: Path, xml: str) -> None:
    report_path = workspace / ".remora" / "pytest_report.xml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(xml, encoding="utf-8")


def test_analyze_signature_with_types(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/analyze_signature.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "node_text_input": "def add(a: int, b: int = 1) -> int:\n    return a + b\n",
            "target_file_input": None,
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "analyze_signature")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["function_name"] == "add"
    assert payload["return_type"] == "int"
    assert payload["parameters"][0] == {"name": "a", "type": "int", "default": None}
    assert payload["parameters"][1] == {"name": "b", "type": "int", "default": 1}
    assert payload["is_async"] is False


def test_analyze_signature_without_types(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/analyze_signature.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "node_text_input": "def greet(name=\"World\"):\n    return f'Hi {name}'\n",
            "target_file_input": None,
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "analyze_signature")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["function_name"] == "greet"
    assert payload["parameters"][0] == {"name": "name", "type": None, "default": "World"}
    assert payload["return_type"] is None


def test_read_existing_tests_returns_empty(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/read_existing_tests.pym")
    _write_sample_module(tmp_path)
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"node_text_input": None, "target_file_input": "sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "read_existing_tests")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["content"] == ""
    assert payload["path"] is None


def test_write_test_file_creates_file(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/write_test_file.pym")
    externals = build_file_externals(
        tmp_path,
        include_read_file=False,
        include_file_exists=False,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"content": "import sample\n", "path_value": "tests/test_sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "write_test_file")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["success"] is True
    assert (tmp_path / "tests" / "test_sample.py").exists()


def test_pytest_config_returns_empty(tmp_path: Path) -> None:
    path = _script_path("agents/test/context/pytest_config.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(path=path, inputs={"noop": False}, externals=externals, grail_dir=grail_dir)

    assert_artifacts(grail_dir, "pytest_config")
    assert result == ""


def test_run_tests_passing(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/run_tests.pym")
    _write_sample_module(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_sample.py"
    test_file.write_text(
        "import sample\n\n\ndef test_add():\n    assert sample.add(1, 2) == 3\n",
        encoding="utf-8",
    )

    import shutil
    if not shutil.which("pytest"):
        pytest.skip("pytest not installed")

    externals = build_file_externals(
        tmp_path,
        include_write_file=False,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"path_input": "tests/test_sample.py", "target_file_input": "sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "run_tests")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["failed"] == 0
    assert payload["errors"] == 0
    assert payload["passed"] >= 1


def test_run_tests_failing(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/run_tests.pym")
    _write_sample_module(tmp_path)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_sample.py"
    test_file.write_text(
        "import sample\n\n\ndef test_add():\n    assert sample.add(1, 2) == 4\n",
        encoding="utf-8",
    )

    import shutil
    if not shutil.which("pytest"):
        pytest.skip("pytest not installed")

    externals = build_file_externals(
        tmp_path,
        include_write_file=False,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"path_input": "tests/test_sample.py", "target_file_input": "sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "run_tests")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["failed"] >= 1
    assert payload["failures"]


def test_submit_builds_agent_result(tmp_path: Path) -> None:
    path = _script_path("agents/test/tools/submit_result.pym")
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "summary": "Added tests",
            "tests_generated": 2,
            "tests_passing": 2,
            "changed_files": ["tests/test_sample.py"],
            "workspace_id": "test-123",
        },
        externals={},
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "submit_result")
    assert result["status"] == "success"
    assert result["workspace_id"] == "test-123"
    assert result["details"]["tests_generated"] == 2
