from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.utils.grail_runtime import assert_artifacts, build_file_externals, run_script
from tests.utils.tool_contract import assert_valid_tool_result

pytestmark = pytest.mark.grail_runtime


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path(relative: str) -> Path:
    return _repo_root() / relative


def _write_sample(workspace: Path) -> Path:
    target = workspace / "sample.py"
    target.write_text("def add():\n    return 1+2\n", encoding="utf-8")
    return target


def test_run_linter_parses_issues(tmp_path: Path) -> None:
    path = _script_path("agents/lint/tools/run_linter.pym")
    _write_sample(tmp_path)

    # ensure ruff is available
    import shutil
    if not shutil.which("ruff"):
        pytest.skip("ruff not installed")

    externals = build_file_externals(
        tmp_path,
        include_write_file=False,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"check_only": True, "target_file_input": "sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "run_linter")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["total"] == 1
    assert payload["fixable_count"] == 1
    assert payload["issues"][0]["code"] == "E225"
    assert payload["issues"][0]["fixable"] is True


def test_apply_fix_updates_file(tmp_path: Path) -> None:
    path = _script_path("agents/lint/tools/apply_fix.pym")
    target = _write_sample(tmp_path)

    import shutil
    if not shutil.which("ruff"):
        pytest.skip("ruff not installed")

    externals = build_file_externals(
        tmp_path,
        include_write_file=False,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"issue_code": "E225", "line_number": 2, "target_file_input": "sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "apply_fix")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["success"] is True
    assert "Applied fix" in payload["message"]
    assert "1 + 2" in target.read_text(encoding="utf-8")


def test_read_file_returns_content_and_lines(tmp_path: Path) -> None:
    path = _script_path("agents/lint/tools/read_file.pym")
    target = _write_sample(tmp_path)
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"target_file_input": "sample.py"},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "read_file")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["content"] == target.read_text(encoding="utf-8")
    assert payload["lines"] == 2


def test_ruff_config_returns_empty_when_missing(tmp_path: Path) -> None:
    path = _script_path("agents/lint/context/ruff_config.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(path=path, inputs={"noop": False}, externals=externals, grail_dir=grail_dir)

    assert_artifacts(grail_dir, "ruff_config")
    assert result == ""


def test_submit_builds_agent_result(tmp_path: Path) -> None:
    path = _script_path("agents/lint/tools/submit_result.pym")
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "summary": "Fixed lint issues",
            "issues_fixed": 2,
            "issues_remaining": 0,
            "changed_files": ["sample.py"],
            "workspace_id": "lint-123",
        },
        externals={},
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "submit_result")
    assert result["status"] == "success"
    assert result["workspace_id"] == "lint-123"
    assert result["details"]["issues_fixed"] == 2


def test_lint_flow_updates_file(tmp_path: Path) -> None:
    run_linter_path = _script_path("agents/lint/tools/run_linter.pym")
    apply_fix_path = _script_path("agents/lint/tools/apply_fix.pym")
    submit_path = _script_path("agents/lint/tools/submit_result.pym")

    target = _write_sample(tmp_path)

    import shutil
    if not shutil.which("ruff"):
        pytest.skip("ruff not installed")

    grail_dir = tmp_path / ".grail"

    lint_result = run_script(
        path=run_linter_path,
        inputs={"check_only": True, "target_file_input": "sample.py"},
        externals=build_file_externals(
            tmp_path,
            include_write_file=False,
        ),
        grail_dir=grail_dir,
    )
    fix_result = run_script(
        path=apply_fix_path,
        inputs={"issue_code": "E225", "line_number": 2, "target_file_input": "sample.py"},
        externals=build_file_externals(
            tmp_path,
            include_write_file=False,
        ),
        grail_dir=grail_dir,
    )
    submit_result = run_script(
        path=submit_path,
        inputs={
            "summary": "Fixed 1 issue",
            "issues_fixed": 1,
            "issues_remaining": 0,
            "changed_files": ["sample.py"],
            "workspace_id": "lint-flow",
        },
        externals={},
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "run_linter")
    assert_artifacts(grail_dir, "apply_fix")
    assert_artifacts(grail_dir, "submit_result")
    assert_valid_tool_result(lint_result)
    assert_valid_tool_result(fix_result)
    assert lint_result["result"]["fixable_count"] == 1
    assert fix_result["result"]["success"] is True
    assert submit_result["status"] == "success"
    assert "1 + 2" in target.read_text(encoding="utf-8")
