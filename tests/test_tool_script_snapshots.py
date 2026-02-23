"""Tool script output tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.utils.grail_runtime import build_file_externals, run_script
from tests.utils.tool_contract import assert_valid_tool_result


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path(relative: str) -> Path:
    return _repo_root() / relative


class TestLintToolSnapshots:
    def test_run_linter_clean_file_output(self, tmp_path: Path) -> None:
        """Lint tool output for a clean file should be structured."""
        path = _script_path("agents/lint/tools/run_linter.pym")
        target = tmp_path / "sample.py"
        target.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

        import shutil
        if not shutil.which("ruff"):
            pytest.skip("ruff not installed")

        externals = build_file_externals(tmp_path, include_write_file=False)
        grail_dir = tmp_path / ".grail"

        result = run_script(
            path=path,
            inputs={"check_only": True, "target_file_input": "sample.py"},
            externals=externals,
            grail_dir=grail_dir,
        )

        assert_valid_tool_result(result)
        payload = result["result"]
        assert payload["total"] == 0
        assert payload["fixable_count"] == 0
        assert payload["issues"] == []
        assert result["outcome"] == "success"

    def test_run_linter_issues_found_output(self, tmp_path: Path) -> None:
        """Lint tool output with issues should be structured."""
        path = _script_path("agents/lint/tools/run_linter.pym")
        target = tmp_path / "sample.py"
        target.write_text("import os\ndef add(a:int,b:int)->int:\n    return a+b\n", encoding="utf-8")

        import shutil
        if not shutil.which("ruff"):
            pytest.skip("ruff not installed")

        externals = build_file_externals(tmp_path, include_write_file=False)
        grail_dir = tmp_path / ".grail"

        result = run_script(
            path=path,
            inputs={"check_only": True, "target_file_input": "sample.py"},
            externals=externals,
            grail_dir=grail_dir,
        )

        assert_valid_tool_result(result)
        payload = result["result"]
        assert payload["total"] == 1
        assert payload["fixable_count"] == 1
        assert payload["issues"][0]["code"] == "F401"
        assert result["outcome"] == "partial"
