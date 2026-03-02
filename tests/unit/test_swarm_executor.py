"""Tests for SwarmExecutor — the reactive agent execution engine.

Tests cover:
- Prompt building logic (_build_prompt)
- Bundle path resolution (_resolve_bundle_path)
- Model name resolution (_resolve_model_name)
- Language tag helper (_lang_tag_for)
- AgentNode → CSTNode conversion (_agent_node_to_cst_node)
- Connection pooling (LLM client reuse)
- EventStore observer wiring
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode
from remora.core.config import Config
from remora.core.swarm_executor import SwarmExecutor, _lang_tag_for, _agent_node_to_cst_node


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides: Any) -> Config:
    defaults = {
        "project_path": str(tmp_path),
        "bundle_root": str(tmp_path / "agents"),
        "bundle_mapping": {"function": "code", "file": "file"},
        "model_base_url": "http://localhost:8000/v1",
        "model_default": "test/model",
        "model_api_key": "test-key",
        "swarm_root": str(tmp_path / ".remora"),
        "swarm_id": "test-swarm",
        "max_concurrency": 4,
        "max_turns": 3,
        "truncation_limit": 512,
        "timeout_s": 10.0,
        "chat_history_limit": 5,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_node(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "agent_func_1",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "billing.calculate_total",
        "file_path": "src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "start_byte": 0,
        "end_byte": 0,
        "source_code": "def calculate_total(items): return sum(items)",
        "source_hash": "abc123",
        "parent_id": None,
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


# =========================================================================
# 1. _lang_tag_for — pure function
# =========================================================================


class TestLangTagFor:
    """Verify markdown language tag lookup from file paths."""

    def test_python_file(self):
        assert _lang_tag_for("src/main.py") == "python"

    def test_typescript_file(self):
        assert _lang_tag_for("src/app.ts") == "typescript"

    def test_javascript_file(self):
        assert _lang_tag_for("src/app.js") == "javascript"

    def test_rust_file(self):
        assert _lang_tag_for("src/main.rs") == "rust"

    def test_go_file(self):
        assert _lang_tag_for("cmd/main.go") == "go"

    def test_yaml_file(self):
        assert _lang_tag_for("config.yaml") == "yaml"

    def test_yml_file(self):
        assert _lang_tag_for("config.yml") == "yaml"

    def test_json_file(self):
        assert _lang_tag_for("package.json") == "json"

    def test_toml_file(self):
        assert _lang_tag_for("pyproject.toml") == "toml"

    def test_markdown_file(self):
        assert _lang_tag_for("README.md") == "markdown"

    def test_bash_file(self):
        assert _lang_tag_for("build.sh") == "bash"

    def test_unknown_extension_returns_empty(self):
        assert _lang_tag_for("data.xyz") == ""

    def test_no_extension_returns_empty(self):
        assert _lang_tag_for("Makefile") == ""

    def test_case_insensitive(self):
        assert _lang_tag_for("src/Main.PY") == "python"


# =========================================================================
# 2. _agent_node_to_cst_node — conversion helper
# =========================================================================


class TestAgentNodeToCstNode:
    """Verify AgentNode -> CSTNode conversion."""

    def test_basic_conversion(self):
        node = _make_node()
        cst = _agent_node_to_cst_node(node)
        assert cst.node_id == "agent_func_1"
        assert cst.node_type == "function"
        assert cst.name == "calculate_total"
        assert cst.full_name == "billing.calculate_total"
        assert cst.file_path == "src/billing.py"
        assert cst.start_line == 10
        assert cst.end_line == 25

    def test_source_code_maps_to_text(self):
        node = _make_node(source_code="def foo(): pass")
        cst = _agent_node_to_cst_node(node)
        assert cst.text == "def foo(): pass"

    def test_byte_offsets_preserved(self):
        node = _make_node(start_byte=100, end_byte=500)
        cst = _agent_node_to_cst_node(node)
        assert cst.start_byte == 100
        assert cst.end_byte == 500


# =========================================================================
# 3. _resolve_bundle_path
# =========================================================================


class TestResolveBundlePath:
    """Verify bundle path resolution from config mapping."""

    @patch("remora.core.swarm_executor.build_client")
    def test_mapped_node_type(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path, bundle_mapping={"function": "code"})
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node(node_type="function")
        path = executor._resolve_bundle_path(node)
        assert path == Path(config.bundle_root) / "code"

    @patch("remora.core.swarm_executor.build_client")
    def test_unmapped_node_type_returns_bundle_root(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path, bundle_mapping={"function": "code"})
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node(node_type="module")
        path = executor._resolve_bundle_path(node)
        assert path == Path(config.bundle_root)


# =========================================================================
# 4. _build_prompt
# =========================================================================


class TestBuildPrompt:
    """Verify prompt construction from AgentNode and context."""

    @patch("remora.core.swarm_executor.build_client")
    def test_prompt_contains_target_info(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path)
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        prompt = executor._build_prompt(node, cst_node, {})
        assert "billing.calculate_total" in prompt
        assert "src/billing.py" in prompt
        assert "Lines: 10-25" in prompt

    @patch("remora.core.swarm_executor.build_client")
    def test_prompt_includes_code_when_available(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path)
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        files = {"src/billing.py": "def calculate_total(items): return sum(items)"}
        prompt = executor._build_prompt(node, cst_node, files)
        assert "## Code" in prompt
        assert "def calculate_total" in prompt
        assert "```python" in prompt

    @patch("remora.core.swarm_executor.build_client")
    def test_prompt_includes_trigger_event(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path)
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)

        class FakeTrigger:
            content = "file changed"

        prompt = executor._build_prompt(node, cst_node, {}, trigger_event=FakeTrigger())
        assert "## Trigger Event" in prompt
        assert "file changed" in prompt

    @patch("remora.core.swarm_executor.build_client")
    def test_prompt_includes_chat_history(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path)
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        chat_history = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "I fixed it"},
        ]
        prompt = executor._build_prompt(node, cst_node, {}, chat_history=chat_history, requires_context=True)
        assert "## Recent Chat History" in prompt
        assert "fix the bug" in prompt
        assert "I fixed it" in prompt

    @patch("remora.core.swarm_executor.build_client")
    def test_prompt_skips_history_when_requires_context_false(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path)
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        chat_history = [{"role": "user", "content": "fix the bug"}]
        prompt = executor._build_prompt(node, cst_node, {}, chat_history=chat_history, requires_context=False)
        assert "## Recent Chat History" not in prompt

    @patch("remora.core.swarm_executor.build_client")
    def test_prompt_respects_chat_history_limit(self, mock_build_client, tmp_path):
        config = _make_config(tmp_path, chat_history_limit=2)
        mock_build_client.return_value = MagicMock()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        chat_history = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "resp2"},
            {"role": "user", "content": "msg3"},
        ]
        prompt = executor._build_prompt(node, cst_node, {}, chat_history=chat_history, requires_context=True)
        # Only the last 2 entries should be included
        assert "msg1" not in prompt
        assert "resp1" not in prompt
        assert "resp2" in prompt
        assert "msg3" in prompt


# =========================================================================
# 5. Connection Pooling — LLM client created once
# =========================================================================


class TestConnectionPooling:
    """Verify that the LLM client is created once in __init__."""

    @patch("remora.core.swarm_executor.build_client")
    def test_client_created_in_init(self, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        config = _make_config(tmp_path)
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        mock_build_client.assert_called_once()
        assert executor._client is mock_build_client.return_value

    @patch("remora.core.swarm_executor.build_client")
    def test_client_receives_config_values(self, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        config = _make_config(
            tmp_path,
            model_base_url="http://custom:9999/v1",
            model_api_key="my-key",
            model_default="custom/model",
            timeout_s=42.0,
        )
        SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        call_args = mock_build_client.call_args[0][0]
        assert call_args["base_url"] == "http://custom:9999/v1"
        assert call_args["api_key"] == "my-key"
        assert call_args["model"] == "custom/model"
        assert call_args["timeout"] == 42.0


# =========================================================================
# 6. _resolve_model_name
# =========================================================================


class TestResolveModelName:
    """Verify model name resolution from bundle.yaml or config fallback."""

    @patch("remora.core.swarm_executor.build_client")
    def test_falls_back_to_config_default(self, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        config = _make_config(tmp_path, model_default="default/model")
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        # Non-existent bundle path -> falls back to config default
        manifest = MagicMock(model="")
        model = executor._resolve_model_name(tmp_path / "nonexistent", manifest)
        assert model == "default/model"

    @patch("remora.core.swarm_executor.build_client")
    def test_reads_from_bundle_yaml(self, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        config = _make_config(tmp_path, model_default="default/model")
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        # Create a bundle.yaml with a model override
        bundle_dir = tmp_path / "agents" / "code"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "bundle.yaml").write_text("model:\n  id: custom/override\n")

        manifest = MagicMock(model="")
        model = executor._resolve_model_name(bundle_dir, manifest)
        assert model == "custom/override"
