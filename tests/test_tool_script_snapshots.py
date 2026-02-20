"""Snapshot tests for tool script outputs."""

from __future__ import annotations

import json
from pathlib import Path

from tests.utils.grail_runtime import build_file_externals, run_script


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path(relative: str) -> Path:
    return _repo_root() / relative


def _normalize_lint_output(result: dict) -> dict:
    if "error" in result:
        return {"error": result["error"]}
    return result


class TestLintToolSnapshots:
    def test_run_linter_clean_file_output(self, snapshot, tmp_path: Path) -> None:
        """Lint tool output for a clean file should match snapshot."""
        path = _script_path("agents/lint/tools/run_linter.pym")
        target = tmp_path / "sample.py"
        target.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

        def fake_run(_: str, __: list[str]) -> dict[str, object]:
            return {"exit_code": 0, "stdout": "", "stderr": ""}

        externals = build_file_externals(tmp_path, run_command=fake_run, include_write_file=False)
        grail_dir = tmp_path / ".grail"

        result = run_script(
            path=path,
            inputs={"check_only": True, "target_file_input": "sample.py"},
            externals=externals,
            grail_dir=grail_dir,
        )

        normalized = _normalize_lint_output(result)
        assert normalized == snapshot

    def test_run_linter_issues_found_output(self, snapshot, tmp_path: Path) -> None:
        """Lint tool output with issues should match snapshot."""
        path = _script_path("agents/lint/tools/run_linter.pym")
        target = tmp_path / "sample.py"
        target.write_text("def add(a:int,b:int)->int:\n    return a+b\n", encoding="utf-8")

        payload = [
            {
                "code": "E225",
                "message": "missing whitespace around operator",
                "location": {"row": 1, "column": 10},
                "fix": {"applicability": "safe"},
            }
        ]

        def fake_run(_: str, __: list[str]) -> dict[str, object]:
            return {"exit_code": 1, "stdout": json.dumps(payload), "stderr": ""}

        externals = build_file_externals(tmp_path, run_command=fake_run, include_write_file=False)
        grail_dir = tmp_path / ".grail"

        result = run_script(
            path=path,
            inputs={"check_only": True, "target_file_input": "sample.py"},
            externals=externals,
            grail_dir=grail_dir,
        )

        normalized = _normalize_lint_output(result)
        assert normalized == snapshot
