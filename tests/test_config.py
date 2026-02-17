from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from remora.cli import app
from remora.config import load_config, serialize_config
from remora.errors import CONFIG_003, CONFIG_004


def _write_subagent_files(agents_dir: Path) -> None:
    for name in ["lint", "test", "docstring", "sample_data"]:
        subagent_dir = agents_dir / name
        subagent_dir.mkdir(parents=True, exist_ok=True)
        subagent_file = subagent_dir / f"{name}_subagent.yaml"
        subagent_file.write_text("", encoding="utf-8")


def test_default_config_loads_without_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.runner.max_turns == 20
    assert config.queries == ["function_def", "class_def"]
    assert config.agents_dir == (tmp_path / "agents").resolve()
    assert "lint" in config.operations


def test_yaml_overrides_and_cli_overrides(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "queries": ["file"],
                "runner": {"max_turns": 10},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path, {"runner": {"max_turns": 18}})
    assert config.runner.max_turns == 18
    assert config.queries == ["file"]


def test_invalid_yaml_type_exits_with_config_003(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    config_path = tmp_path / "remora.yaml"
    config_path.write_text("runner:\n  max_turns: nope\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "--config", str(config_path)])
    assert result.exit_code == 3
    assert CONFIG_003 in result.output


def test_config_command_outputs_yaml(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "queries": ["file"],
                "runner": {"max_turns": 10},
            }
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["config", "--config", str(config_path), "--format", "yaml", "--max-turns", "25"],
    )
    expected = serialize_config(load_config(config_path, {"runner": {"max_turns": 25}}))
    assert result.exit_code == 0
    output_data = yaml.safe_load(result.output)
    assert output_data == expected


def test_missing_agents_dir_returns_config_004(tmp_path: Path) -> None:
    config_path = tmp_path / "remora.yaml"
    config_path.write_text("agents_dir: missing_agents\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "--config", str(config_path)])
    assert result.exit_code == 3
    assert CONFIG_004 in result.output
