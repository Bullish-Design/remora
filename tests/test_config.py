from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from remora.core.config import DEFAULT_IGNORE_PATTERNS, ErrorPolicy, RemoraConfig, load_config, serialize_config


def _write_config(tmp_path: Path, data: dict) -> Path:
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_path


def _sample_payload() -> dict:
    return {
        "bundles": {
            "path": "agents",
            "mapping": {"function": "lint/bundle.yaml"},
        },
        "discovery": {
            "paths": ["src/"],
            "languages": ["python"],
            "max_workers": 2,
        },
        "model": {
            "base_url": "https://api.local/v1",
            "api_key": "secret",
            "default_model": "Qwen/Qwen3-4B",
        },
        "execution": {
            "max_concurrency": 2,
            "error_policy": "continue",
            "timeout": 120,
            "max_turns": 5,
            "truncation_limit": 256,
        },
        "workspace": {"base_path": ".remora/ws", "cleanup_after": "30m"},
    }


def test_load_config_reads_sections(tmp_path: Path) -> None:
    payload = _sample_payload()
    config_path = _write_config(tmp_path, payload)

    cfg = load_config(config_path)

    assert cfg.model.base_url == "https://api.local/v1"
    assert cfg.model.api_key == "secret"
    assert cfg.bundles.mapping["function"] == "lint/bundle.yaml"
    assert cfg.discovery.paths == ("src/",)
    assert cfg.discovery.languages == ("python",)
    assert cfg.execution.error_policy == ErrorPolicy.CONTINUE
    assert cfg.workspace.base_path == ".remora/ws"


def test_serialize_config_round_trips(tmp_path: Path) -> None:
    payload = _sample_payload()
    config_path = _write_config(tmp_path, payload)
    cfg = load_config(config_path)
    serialized = serialize_config(cfg)
    assert serialized["bundles"] == payload["bundles"]
    assert serialized["discovery"] == payload["discovery"]
    assert serialized["model"] == payload["model"]
    assert serialized["execution"] == payload["execution"]
    assert serialized["workspace"] == {
        **payload["workspace"],
        "ignore_patterns": list(DEFAULT_IGNORE_PATTERNS),
        "ignore_dotfiles": True,
    }


def test_missing_config_file_returns_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "remora.yaml"
    cfg = load_config(missing)
    assert isinstance(cfg, RemoraConfig)
    assert cfg.model.base_url == "http://localhost:8000/v1"


def test_env_override_modifies_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _sample_payload()
    config_path = _write_config(tmp_path, payload)
    monkeypatch.setenv("REMORA_MODEL_BASE_URL", "https://override/v2")
    cfg = load_config(config_path)
    assert cfg.model.base_url == "https://override/v2"
