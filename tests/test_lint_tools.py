from __future__ import annotations

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import json

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


def _write_sample(workspace: Path) -> Path:
    target = workspace / "sample.py"
    target.write_text("def add():\n    return 1+2\n", encoding="utf-8")
    return target


def test_run_linter_parses_issues(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/lint/tools/run_linter.pym", "run_linter")
    _write_sample(tmp_path)
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")

    def fake_run(_: list[str]) -> SimpleNamespace:
        payload = [
            {
                "code": "E225",
                "message": "missing whitespace around operator",
                "location": {"row": 2, "column": 12},
                "fix": {"applicability": "safe"},
            }
        ]
        return SimpleNamespace(returncode=1, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(module, "_run_command", fake_run)

    result = module.run({"check_only": True})

    assert result["total"] == 1
    assert result["fixable_count"] == 1
    assert result["issues"][0]["code"] == "E225"
    assert result["issues"][0]["fixable"] is True


def test_apply_fix_updates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/lint/tools/apply_fix.pym", "apply_fix")
    target = _write_sample(tmp_path)
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")

    def fake_run(_: list[str]) -> SimpleNamespace:
        target.write_text("def add():\n    return 1 + 2\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module, "_run_command", fake_run)

    result = module.run({"issue_code": "E225", "line_number": 2})

    assert result["success"] is True
    assert "Applied fix" in result["message"]
    assert "1 + 2" in target.read_text(encoding="utf-8")


def test_read_file_returns_content_and_lines(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/lint/tools/read_file.pym", "read_file")
    target = _write_sample(tmp_path)
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")

    result = module.run({})

    assert result["content"] == target.read_text(encoding="utf-8")
    assert result["lines"] == 2


def test_ruff_config_returns_empty_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/lint/context/ruff_config.pym", "ruff_config")
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    assert module.run() == ""


def test_submit_builds_agent_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(_repo_root() / "agents/lint/tools/submit.pym", "submit")
    monkeypatch.setenv("REMORA_WORKSPACE_ID", "lint-123")

    result = module.run(
        {
            "summary": "Fixed lint issues",
            "issues_fixed": 2,
            "issues_remaining": 0,
            "changed_files": ["sample.py"],
        }
    )

    assert result["status"] == "success"
    assert result["workspace_id"] == "lint-123"
    assert result["details"]["issues_fixed"] == 2


def test_lint_flow_updates_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_linter = _load_module(_repo_root() / "agents/lint/tools/run_linter.pym", "run_linter_flow")
    apply_fix = _load_module(_repo_root() / "agents/lint/tools/apply_fix.pym", "apply_fix_flow")
    submit = _load_module(_repo_root() / "agents/lint/tools/submit.pym", "submit_flow")

    target = _write_sample(tmp_path)
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("REMORA_TARGET_FILE", "sample.py")
    monkeypatch.setenv("REMORA_WORKSPACE_ID", "lint-flow")

    def fake_check(_: list[str]) -> SimpleNamespace:
        payload = [
            {
                "code": "E225",
                "message": "missing whitespace around operator",
                "location": {"row": 2, "column": 12},
                "fix": {"applicability": "safe"},
            }
        ]
        return SimpleNamespace(returncode=1, stdout=json.dumps(payload), stderr="")

    def fake_fix(_: list[str]) -> SimpleNamespace:
        target.write_text("def add():\n    return 1 + 2\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_linter, "_run_command", fake_check)
    monkeypatch.setattr(apply_fix, "_run_command", fake_fix)

    lint_result = run_linter.run({"check_only": True})
    fix_result = apply_fix.run({"issue_code": "E225", "line_number": 2})
    submit_result = submit.run(
        {
            "summary": "Fixed 1 issue",
            "issues_fixed": 1,
            "issues_remaining": 0,
            "changed_files": ["sample.py"],
        }
    )

    assert lint_result["fixable_count"] == 1
    assert fix_result["success"] is True
    assert submit_result["status"] == "success"
    assert "1 + 2" in target.read_text(encoding="utf-8")
