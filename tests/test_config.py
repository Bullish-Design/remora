from pathlib import Path

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from remora.cli import app
from remora.config import ConfigError, load_config, serialize_config


def _write_config(tmp_path: Path, data: dict) -> Path:
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_path


def _sample_payload() -> dict:
    return {
        "model_base_url": "https://api.local/v1",
        "api_key": "secret",
        "bundle_metadata": {
            "lint": {
                "path": "agents/lint/bundle.yaml",
                "node_types": ["function"],
                "priority": 10,
                "requires_context": True,
            }
        },
        "workspace": {"base_path": ".remora/ws", "cleanup_after": "30m"},
    }


def test_load_config_reads_metadata(tmp_path: Path) -> None:
    payload = _sample_payload()
    config_path = _write_config(tmp_path, payload)

    cfg = load_config(config_path)

    assert cfg.model_base_url == "https://api.local/v1"
    assert cfg.api_key == "secret"
    assert "lint" in cfg.bundle_metadata
    metadata = cfg.bundle_metadata["lint"]
    assert metadata.node_types == ("function",)
    assert metadata.priority == 10
    assert metadata.requires_context is True
    assert cfg.workspace.base_path == Path(".remora/ws")


def test_serialize_config_round_trips(tmp_path: Path) -> None:
    payload = _sample_payload()
    config_path = _write_config(tmp_path, payload)
    cfg = load_config(config_path)
    serialized = serialize_config(cfg)
    assert serialized == payload


def test_config_command_outputs_yaml(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _sample_payload())
    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config_path)])
    assert result.exit_code == 0
    assert "model_base_url" in result.output


def test_config_command_supports_json(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _sample_payload())
    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config_path), "--format", "json"])
    assert result.exit_code == 0
    assert "{\n" in result.output


def test_missing_config_file_errors(tmp_path: Path) -> None:
    missing = tmp_path / "remora.yaml"
    with pytest.raises(ConfigError):
        load_config(missing)


def test_env_override_modifies_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _sample_payload()
    config_path = _write_config(tmp_path, payload)
    monkeypatch.setenv("REMORA_MODEL_BASE_URL", "https://override/v2")
    cfg = load_config(config_path)
    assert cfg.model_base_url == "https://override/v2"
