"""Tests for LLM config unification — item 2.3.

All LLM-touching code should read model name, base URL, and API key from
the canonical Config object rather than hardcoding values.
"""

from __future__ import annotations

import pytest

from remora.core.config import Config


# ---------------------------------------------------------------------------
# ChatConfig should derive defaults from Config
# ---------------------------------------------------------------------------


class TestChatConfigFromConfig:
    """ChatConfig.from_config() should mirror Config's LLM fields."""

    def test_from_config_copies_model_fields(self) -> None:
        from remora.core.chat import ChatConfig

        cfg = Config(
            model_base_url="http://my-server:9000/v1",
            model_default="my-org/my-model",
            model_api_key="sk-secret",
        )
        chat_cfg = ChatConfig.from_config(cfg, workspace_path="/tmp/ws", system_prompt="hello")
        assert chat_cfg.model_base_url == "http://my-server:9000/v1"
        assert chat_cfg.model_name == "my-org/my-model"
        assert chat_cfg.model_api_key == "sk-secret"

    def test_from_config_preserves_workspace_and_prompt(self) -> None:
        from remora.core.chat import ChatConfig

        cfg = Config()
        chat_cfg = ChatConfig.from_config(cfg, workspace_path="/ws", system_prompt="sys")
        assert chat_cfg.workspace_path == "/ws"
        assert chat_cfg.system_prompt == "sys"

    def test_from_config_uses_config_defaults(self) -> None:
        """When Config uses defaults, ChatConfig should too."""
        from remora.core.chat import ChatConfig

        cfg = Config()
        chat_cfg = ChatConfig.from_config(cfg, workspace_path="/ws", system_prompt="sys")
        assert chat_cfg.model_base_url == cfg.model_base_url
        assert chat_cfg.model_name == cfg.model_default
        assert chat_cfg.model_api_key == cfg.model_api_key

    def test_chatconfig_defaults_match_config_defaults(self) -> None:
        """ChatConfig bare defaults should now align with Config bare defaults."""
        from remora.core.chat import ChatConfig

        cfg = Config()
        chat_cfg = ChatConfig(workspace_path="/ws", system_prompt="sys")
        assert chat_cfg.model_base_url == cfg.model_base_url
        assert chat_cfg.model_name == cfg.model_default


# ---------------------------------------------------------------------------
# lsp/__main__.py should read from Config, not hardcode
# ---------------------------------------------------------------------------


class TestLspMainUsesConfig:
    """The LSP entry point must create LLMClient from Config values."""

    def test_lsp_main_reads_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify that main() loads Config and passes its values to LLMClient."""
        captured: dict = {}

        # Stub LLMClient to capture init args
        class FakeLLMClient:
            def __init__(self, base_url: str, model: str, api_key: str = "EMPTY"):
                captured["base_url"] = base_url
                captured["model"] = model
                captured["api_key"] = api_key

        # Stub AgentRunner to do nothing
        class FakeRunner:
            def __init__(self, **kwargs):
                pass

        # Stub server
        class FakeServer:
            event_store = None
            subscriptions = None
            swarm_state = None
            runner = None

            def start_io(self):
                raise _StopSentinel()

            def feature(self, uri):
                return lambda fn: fn

        class _StopSentinel(Exception):
            pass

        fake_server = FakeServer()

        # Stub load_config to return a known Config
        test_config = Config(
            model_base_url="http://test-host:1234/v1",
            model_default="test-org/test-model",
            model_api_key="test-api-key",
        )

        # Monkeypatch the actual source module so local imports resolve to our stubs
        monkeypatch.setattr("remora.core.config.load_config", lambda path=None: test_config)

        # Monkeypatch _get_server at module level
        import remora.lsp.__main__ as lsp_main_mod

        monkeypatch.setattr(lsp_main_mod, "_get_server", lambda: fake_server)

        # Monkeypatch the runner module imports
        import remora.lsp.runner as runner_mod

        monkeypatch.setattr(runner_mod, "LLMClient", FakeLLMClient)
        monkeypatch.setattr(runner_mod, "AgentRunner", FakeRunner)

        # Make _setup_logging not create filesystem artifacts
        monkeypatch.setattr(
            lsp_main_mod,
            "_setup_logging",
            lambda: __import__("logging").getLogger("test"),
        )

        with pytest.raises(_StopSentinel):
            lsp_main_mod.main()

        assert captured["base_url"] == "http://test-host:1234/v1"
        assert captured["model"] == "test-org/test-model"
        assert captured["api_key"] == "test-api-key"


# ---------------------------------------------------------------------------
# No hardcoded LLM URLs/models remain in source files
# ---------------------------------------------------------------------------


class TestNoHardcodedLLMValues:
    """Ensure the old hardcoded values are gone from the three source files."""

    def test_lsp_main_no_hardcoded_model(self) -> None:
        import inspect
        import remora.lsp.__main__ as mod

        source = inspect.getsource(mod.main)
        assert "Qwen/Qwen3-4B-Instruct-2507-FP8" not in source
        assert "remora-server:8000" not in source

    def test_chat_config_no_hardcoded_model(self) -> None:
        import inspect
        from remora.core.chat import ChatConfig

        source = inspect.getsource(ChatConfig)
        assert "Qwen/Qwen3-4B-Instruct-2507-FP8" not in source
        assert "remora-server:8000" not in source
