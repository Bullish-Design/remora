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


def test_sample_data_analyze_signature(tmp_path: Path) -> None:
    path = _script_path("agents/sample_data/tools/analyze_signature.pym")
    externals = build_file_externals(tmp_path, include_write_file=False)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "node_text_input": "def total(price: float, quantity: int = 1) -> float:\n    return price * quantity\n",
            "target_file_input": None,
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "analyze_signature")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["function_name"] == "total"
    assert payload["return_type"] == "float"
    assert payload["parameters"][0] == {"name": "price", "type": "float", "default": None}
    assert payload["parameters"][1] == {"name": "quantity", "type": "int", "default": 1}


def test_write_fixture_file_creates_json(tmp_path: Path) -> None:
    path = _script_path("agents/sample_data/tools/write_fixture_file.pym")
    externals = build_file_externals(tmp_path)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "fixtures": [
                {"price": 9.99, "quantity": 2},
                {"price": 0.0, "quantity": 1},
            ],
            "format_input": "json",
            "node_text_input": "def total(price: float, quantity: int = 1) -> float:\n    return price * quantity\n",
        },
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "write_fixture_file")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["success"] is True
    assert payload["path"] == "fixtures/total_fixtures.json"
    content = (tmp_path / "fixtures" / "total_fixtures.json").read_text(encoding="utf-8")
    assert json.loads(content)[0]["price"] == 9.99


def test_write_fixture_file_rejects_empty(tmp_path: Path) -> None:
    path = _script_path("agents/sample_data/tools/write_fixture_file.pym")
    externals = build_file_externals(tmp_path)
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={"fixtures": [], "format_input": "json", "node_text_input": None},
        externals=externals,
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "write_fixture_file")
    assert_valid_tool_result(result)
    payload = result["result"]
    assert payload["success"] is False
    assert not (tmp_path / "fixtures").exists()


def test_existing_fixtures_returns_empty(tmp_path: Path) -> None:
    path = _script_path("agents/sample_data/context/existing_fixtures.pym")
    externals = build_file_externals(
        tmp_path,
        include_read_file=False,
        include_write_file=False,
        include_list_dir=True,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(path=path, inputs={"noop": False}, externals=externals, grail_dir=grail_dir)

    assert_artifacts(grail_dir, "existing_fixtures")
    assert result == []


def test_existing_fixtures_lists_files(tmp_path: Path) -> None:
    path = _script_path("agents/sample_data/context/existing_fixtures.pym")
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "alpha_fixtures.json").write_text("[]", encoding="utf-8")
    (fixtures_dir / "beta_fixtures.json").write_text("[]", encoding="utf-8")
    externals = build_file_externals(
        tmp_path,
        include_read_file=False,
        include_write_file=False,
        include_list_dir=True,
    )
    grail_dir = tmp_path / ".grail"

    result = run_script(path=path, inputs={"noop": False}, externals=externals, grail_dir=grail_dir)

    assert_artifacts(grail_dir, "existing_fixtures")
    assert result == [
        {"name": "alpha_fixtures.json", "path": "fixtures/alpha_fixtures.json"},
        {"name": "beta_fixtures.json", "path": "fixtures/beta_fixtures.json"},
    ]


def test_submit_builds_agent_result(tmp_path: Path) -> None:
    path = _script_path("agents/sample_data/tools/submit.pym")
    grail_dir = tmp_path / ".grail"

    result = run_script(
        path=path,
        inputs={
            "summary": "Generated fixtures",
            "fixtures_generated": 2,
            "changed_files": ["fixtures/total_fixtures.json"],
            "workspace_id": "sample-123",
        },
        externals={},
        grail_dir=grail_dir,
    )

    assert_artifacts(grail_dir, "submit")
    assert result["status"] == "success"
    assert result["workspace_id"] == "sample-123"
    assert result["details"]["fixtures_generated"] == 2
