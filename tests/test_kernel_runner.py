"""Tests for KernelRunner."""

from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from remora.kernel_runner import KernelRunner
from remora.results import AgentStatus


class TestKernelRunner:
    @pytest.fixture
    def mock_node(self):
        node = MagicMock()
        node.node_id = "test-node-id"
        node.name = "test_function"
        node.node_type = "function"
        node.file_path = Path("/test/file.py")
        node.text = "def test_function():\n    pass"
        node.start_line = 1
        node.end_line = 2
        return node

    @pytest.fixture
    def mock_ctx(self):
        ctx = MagicMock()
        ctx.agent_id = "test-agent-id"
        return ctx

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        config.server.base_url = "http://localhost:8000/v1"
        config.server.api_key = "EMPTY"
        config.server.timeout = 120
        config.server.default_adapter = "test-model"
        config.runner.max_tokens = 4096
        config.runner.temperature = 0.1
        config.runner.tool_choice = "auto"
        config.runner.max_history_messages = 50
        config.cairn.home = None
        config.cairn.pool_workers = 4
        config.cairn.timeout = 300
        config.cairn.limits_preset = "default"
        config.cairn.limits_override = {}
        return config

    @pytest.fixture
    def mock_emitter(self):
        return MagicMock()

    def test_summarize_node_short(self, mock_node, mock_ctx, mock_config, mock_emitter, tmp_path):
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()
        (bundle_dir / "tools").mkdir()
        (bundle_dir / "bundle.yaml").write_text(
            """
name: test_agent
version: "1.0"

model:
  plugin: function_gemma

initial_context:
  system_prompt: Test
  user_template: "{{ node_text }}"

max_turns: 5
termination_tool: submit_result

tools:
  - name: submit_result
    registry: grail
    description: Submit result

registries:
  - type: grail
    config:
      agents_dir: tools
"""
        )

        with patch("remora.kernel_runner.load_bundle") as mock_load:
            mock_bundle = MagicMock()
            mock_bundle.name = "test_agent"
            mock_bundle.manifest.model.adapter = None
            mock_bundle.max_turns = 5
            mock_bundle.termination_tool = "submit_result"
            mock_bundle.tool_schemas = []
            mock_bundle.get_plugin.return_value = MagicMock()
            mock_bundle.get_grammar_config.return_value = MagicMock()
            mock_bundle.build_tool_source.return_value = MagicMock()
            mock_load.return_value = mock_bundle

            with patch("remora.kernel_runner.GrailBackend"):
                with patch("remora.kernel_runner.AgentKernel"):
                    runner = KernelRunner(
                        node=mock_node,
                        ctx=mock_ctx,
                        config=mock_config,
                        bundle_path=bundle_dir,
                        event_emitter=mock_emitter,
                    )

                    summary = runner._summarize_node()
                    assert "def test_function" in summary

    def test_parse_status(self, mock_node, mock_ctx, mock_config, mock_emitter, tmp_path):
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()
        (bundle_dir / "tools").mkdir()
        (bundle_dir / "bundle.yaml").write_text(
            """
name: test_agent
version: "1.0"
model:
  plugin: function_gemma
initial_context:
  system_prompt: Test
  user_template: "{{ node_text }}"
max_turns: 5
termination_tool: submit_result
tools:
  - name: submit_result
    registry: grail
    description: Submit result
registries:
  - type: grail
    config:
      agents_dir: tools
"""
        )

        with patch("remora.kernel_runner.load_bundle") as mock_load:
            mock_bundle = MagicMock()
            mock_bundle.name = "test_agent"
            mock_bundle.manifest.model.adapter = None
            mock_bundle.max_turns = 5
            mock_bundle.termination_tool = "submit_result"
            mock_bundle.tool_schemas = []
            mock_bundle.get_plugin.return_value = MagicMock()
            mock_bundle.get_grammar_config.return_value = MagicMock()
            mock_bundle.build_tool_source.return_value = MagicMock()
            mock_load.return_value = mock_bundle

            with patch("remora.kernel_runner.GrailBackend"):
                with patch("remora.kernel_runner.AgentKernel"):
                    runner = KernelRunner(
                        node=mock_node,
                        ctx=mock_ctx,
                        config=mock_config,
                        bundle_path=bundle_dir,
                        event_emitter=mock_emitter,
                    )

                    assert runner._parse_status("success") == AgentStatus.SUCCESS
                    assert runner._parse_status("skipped") == AgentStatus.SKIPPED
                    assert runner._parse_status("failed") == AgentStatus.FAILED
                    assert runner._parse_status("ERROR") == AgentStatus.FAILED
