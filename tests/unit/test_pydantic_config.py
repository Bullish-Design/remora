"""TDD tests for 6.2: Pydantic Config/BaseSettings.

Verifies:
- Config is a Pydantic BaseModel (not stdlib dataclass)
- Config fields are accessible via dot notation
- model_dump() replaces serialize_config()
- Config can be constructed from dict (YAML data) without manual coercion
- Environment variable overrides work via BaseSettings
- serialize_config() still works (delegates to model_dump)
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel


class TestConfigIsPydantic:
    """Config must be a Pydantic BaseModel."""

    def test_is_pydantic(self):
        from remora.core.config import Config

        assert issubclass(Config, BaseModel), "Config must be a Pydantic BaseModel"

    def test_is_not_stdlib_dataclass(self):
        import dataclasses

        from remora.core.config import Config

        assert not dataclasses.is_dataclass(Config), "Config must NOT be a stdlib dataclass"


class TestConfigDefaults:
    """Config should have the same defaults as before."""

    def test_default_construction(self):
        from remora.core.config import Config

        cfg = Config()
        assert cfg.project_path == "."
        assert cfg.discovery_paths == ("src/",)
        assert cfg.discovery_languages is None
        assert cfg.discovery_max_workers == 4
        assert cfg.bundle_root == "agents"
        assert cfg.bundle_mapping == {}
        assert cfg.bundle_mapping_tools == {}
        assert cfg.model_base_url == "http://localhost:8000/v1"
        assert cfg.model_default == "Qwen/Qwen3-4B"
        assert cfg.model_api_key == ""
        assert cfg.swarm_root == ".remora"
        assert cfg.swarm_id == "swarm"
        assert cfg.max_concurrency == 4
        assert cfg.max_turns == 8
        assert cfg.truncation_limit == 1024
        assert cfg.timeout_s == 300.0
        assert cfg.max_trigger_depth == 5
        assert cfg.trigger_cooldown_ms == 1000
        assert cfg.chat_history_limit == 5
        assert cfg.workspace_ignore_dotfiles is True
        assert cfg.nvim_enabled is False
        assert cfg.nvim_socket == ".remora/nvim.sock"

    def test_custom_values(self):
        from remora.core.config import Config

        cfg = Config(
            model_base_url="http://other:9000/v1",
            model_default="my-model",
            max_turns=20,
        )
        assert cfg.model_base_url == "http://other:9000/v1"
        assert cfg.model_default == "my-model"
        assert cfg.max_turns == 20


class TestModelDump:
    """model_dump() must replace serialize_config()."""

    def test_model_dump_returns_dict(self):
        from remora.core.config import Config

        cfg = Config()
        data = cfg.model_dump()
        assert isinstance(data, dict)
        assert "project_path" in data
        assert "model_default" in data

    def test_model_dump_tuples_become_lists(self):
        """model_dump(mode='json') should serialize tuples as lists for YAML/JSON compat."""
        from remora.core.config import Config

        cfg = Config()
        data = cfg.model_dump(mode="json")
        # Tuples are serialized as lists by Pydantic in JSON mode
        assert isinstance(data["discovery_paths"], list)
        assert data["discovery_paths"] == ["src/"]

    def test_serialize_config_delegates_to_model_dump(self):
        """serialize_config() should still work, returning same as model_dump(mode='json')."""
        from remora.core.config import Config, serialize_config

        cfg = Config(model_default="test-model", max_turns=12)
        serialized = serialize_config(cfg)
        dumped = cfg.model_dump(mode="json")
        assert serialized == dumped


class TestListToTupleCoercion:
    """Pydantic should accept lists for tuple fields (from YAML data)."""

    def test_list_coerced_to_tuple(self):
        from remora.core.config import Config

        cfg = Config(discovery_paths=["src/", "lib/"])
        assert cfg.discovery_paths == ("src/", "lib/")
        assert isinstance(cfg.discovery_paths, tuple)

    def test_list_coerced_for_ignore_patterns(self):
        from remora.core.config import Config

        cfg = Config(workspace_ignore_patterns=[".git", "__pycache__"])
        assert cfg.workspace_ignore_patterns == (".git", "__pycache__")
        assert isinstance(cfg.workspace_ignore_patterns, tuple)


class TestBuildConfigFromDict:
    """_build_config / load_config should work with raw YAML dict data."""

    def test_build_from_dict(self):
        from remora.core.config import _build_config

        data = {
            "project_path": "/my/project",
            "discovery_paths": ["src/", "lib/"],
            "model_default": "my-model",
            "max_turns": 15,
        }
        cfg = _build_config(data)
        assert cfg.project_path == "/my/project"
        assert cfg.discovery_paths == ("src/", "lib/")
        assert cfg.model_default == "my-model"
        assert cfg.max_turns == 15


class TestEnvVarOverrides:
    """Config should support environment variable overrides."""

    def test_env_override_model_default(self, monkeypatch):
        from remora.core.config import Config

        monkeypatch.setenv("REMORA_MODEL_DEFAULT", "env-model")
        cfg = Config()
        assert cfg.model_default == "env-model"

    def test_env_override_model_base_url(self, monkeypatch):
        from remora.core.config import Config

        monkeypatch.setenv("REMORA_MODEL_BASE_URL", "http://env:9999/v1")
        cfg = Config()
        assert cfg.model_base_url == "http://env:9999/v1"

    def test_env_override_max_turns(self, monkeypatch):
        from remora.core.config import Config

        monkeypatch.setenv("REMORA_MAX_TURNS", "42")
        cfg = Config()
        assert cfg.max_turns == 42

    def test_explicit_value_overrides_env(self, monkeypatch):
        """Explicitly passed values should still take precedence."""
        from remora.core.config import Config

        monkeypatch.setenv("REMORA_MODEL_DEFAULT", "env-model")
        cfg = Config(model_default="explicit-model")
        assert cfg.model_default == "explicit-model"
