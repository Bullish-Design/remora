from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from remora.cli import app
from remora.config import CairnConfig, load_config, resolve_grail_limits, serialize_config
from remora.errors import CONFIG_003, CONFIG_004


def _write_subagent_files(agents_dir: Path) -> None:
    for name in ["lint", "test", "docstring", "sample_data"]:
        subagent_dir = agents_dir / name
        subagent_dir.mkdir(parents=True, exist_ok=True)
        bundle_file = subagent_dir / "bundle.yaml"
        bundle_file.write_text("", encoding="utf-8")


def test_default_config_loads_without_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.runner.max_turns == 20
    assert config.discovery.query_pack == "remora_core"
    assert config.agents_dir == (tmp_path / "agents").resolve()
    assert "lint" in config.operations


def test_yaml_overrides_and_cli_overrides(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "discovery": {"query_pack": "custom_pack"},
                "runner": {"max_turns": 10},
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path, {"runner": {"max_turns": 18}})
    assert config.runner.max_turns == 18
    assert config.discovery.query_pack == "custom_pack"


def test_invalid_yaml_type_exits_with_config_003(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    config_path = tmp_path / "remora.yaml"
    config_path.write_text("runner:\n  max_turns: nope\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "--config", str(config_path)])
    assert result.exit_code == 1
    assert CONFIG_003 in result.output


def test_config_command_outputs_yaml(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_subagent_files(agents_dir)
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "discovery": {"query_pack": "custom_pack"},
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
    assert result.exit_code == 1
    assert CONFIG_004 in result.output


# ---------------------------------------------------------------------------
# CairnConfig new fields & resolve_grail_limits
# ---------------------------------------------------------------------------


def test_cairn_config_new_fields_have_defaults() -> None:
    """New fields should have sensible defaults without any user config."""
    config = CairnConfig()
    assert config.limits_preset == "default"
    assert config.limits_override == {}
    assert config.pool_workers == 4


@pytest.mark.parametrize("preset", ["strict", "default", "permissive"])
def test_resolve_grail_limits_presets(preset: str) -> None:
    """Each preset maps to the corresponding grail.limits constant."""
    import grail.limits

    expected = {
        "strict": grail.limits.STRICT,
        "default": grail.limits.DEFAULT,
        "permissive": grail.limits.PERMISSIVE,
    }
    config = CairnConfig(limits_preset=preset)
    result = resolve_grail_limits(config)
    assert result == expected[preset]


def test_resolve_grail_limits_with_override() -> None:
    """Overrides merge on top of the preset."""
    config = CairnConfig(limits_preset="default", limits_override={"max_duration": "60s"})
    result = resolve_grail_limits(config)
    assert result["max_duration"] == "60s"
