from __future__ import annotations

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
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


def test_sample_data_analyze_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(
        _repo_root() / "agents/sample_data/tools/analyze_signature.pym",
        "sample_data_analyze_signature",
    )
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def total(price: float, quantity: int = 1) -> float:\n    return price * quantity\n",
    )

    result = module.run({})

    assert result["function_name"] == "total"
    assert result["return_type"] == "float"
    assert result["parameters"][0] == {"name": "price", "type": "float", "default": None}
    assert result["parameters"][1] == {"name": "quantity", "type": "int", "default": 1}


def test_write_fixture_file_creates_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/sample_data/tools/write_fixture_file.pym",
        "sample_data_write_fixture",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv(
        "REMORA_NODE_TEXT",
        "def total(price: float, quantity: int = 1) -> float:\n    return price * quantity\n",
    )

    result = module.run(
        {
            "fixtures": [
                {"price": 9.99, "quantity": 2},
                {"price": 0.0, "quantity": 1},
            ],
            "format": "json",
        }
    )

    assert result["success"] is True
    assert result["path"] == "fixtures/total_fixtures.json"
    content = (tmp_path / "fixtures" / "total_fixtures.json").read_text(encoding="utf-8")
    assert json.loads(content)[0]["price"] == 9.99


def test_write_fixture_file_rejects_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/sample_data/tools/write_fixture_file.pym",
        "sample_data_write_fixture_empty",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    result = module.run({"fixtures": []})

    assert result["success"] is False
    assert not (tmp_path / "fixtures").exists()


def test_existing_fixtures_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/sample_data/context/existing_fixtures.pym",
        "sample_data_existing_fixtures",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    assert module.run() == []


def test_existing_fixtures_lists_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module(
        _repo_root() / "agents/sample_data/context/existing_fixtures.pym",
        "sample_data_existing_fixtures_list",
    )
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "alpha_fixtures.json").write_text("[]", encoding="utf-8")
    (fixtures_dir / "beta_fixtures.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("REMORA_WORKSPACE_DIR", str(tmp_path))

    result = module.run()

    assert result == [
        {"name": "alpha_fixtures.json", "path": "fixtures/alpha_fixtures.json"},
        {"name": "beta_fixtures.json", "path": "fixtures/beta_fixtures.json"},
    ]


def test_submit_builds_agent_result(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module(
        _repo_root() / "agents/sample_data/tools/submit.pym",
        "sample_data_submit",
    )
    monkeypatch.setenv("REMORA_WORKSPACE_ID", "sample-123")

    result = module.run(
        {
            "summary": "Generated fixtures",
            "fixtures_generated": 2,
            "changed_files": ["fixtures/total_fixtures.json"],
        }
    )

    assert result["status"] == "success"
    assert result["workspace_id"] == "sample-123"
    assert result["details"]["fixtures_generated"] == 2
