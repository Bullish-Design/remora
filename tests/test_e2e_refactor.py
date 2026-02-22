"""End-to-end tests for the refactored system."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.kernel_runner import KernelRunner
from remora.results import AgentStatus


class TestE2ERefactor:
    @pytest.fixture
    def sample_bundle(self, tmp_path: Path) -> Path:
        """Create a sample bundle for testing."""
        bundle_dir = tmp_path / "test_bundle"
        bundle_dir.mkdir()
        (bundle_dir / "tools").mkdir()

        (bundle_dir / "bundle.yaml").write_text(
            """
name: test_agent
version: "1.0"

model:
  plugin: function_gemma
  grammar:
    mode: ebnf
    allow_parallel_calls: true
    args_format: permissive

initial_context:
  system_prompt: You are a test agent.
  user_template: "Process: {{ node_text }}"

max_turns: 5
termination_tool: submit_result

tools:
  - name: analyze
    registry: grail
    description: Analyze code

  - name: submit_result
    registry: grail
    description: Submit result
    inputs_override:
      summary:
        type: string
        description: Summary

registries:
  - type: grail
    config:
      agents_dir: tools
""",
            encoding="utf-8",
        )

        return bundle_dir

    @pytest.mark.asyncio
    async def test_kernel_runner_executes(self, sample_bundle: Path) -> None:
        """Verify KernelRunner can execute a simple workflow."""
        mock_node = MagicMock()
        mock_node.node_id = "test-node"
        mock_node.name = "test_func"
        mock_node.node_type = "function"
        mock_node.file_path = Path("/test.py")
        mock_node.text = "def test(): pass"
        mock_node.start_line = 1
        mock_node.end_line = 1

        mock_ctx = MagicMock()
        mock_ctx.agent_id = "test-agent"

        mock_config = MagicMock()
        mock_config.server.base_url = "http://localhost:8000/v1"
        mock_config.server.api_key = "EMPTY"
        mock_config.server.timeout = 60
        mock_config.server.default_adapter = "test"
        mock_config.runner.max_tokens = 2048
        mock_config.runner.temperature = 0.1
        mock_config.runner.tool_choice = "auto"
        mock_config.runner.max_history_messages = 50
        mock_config.cairn.home = None
        mock_config.cairn.pool_workers = 2
        mock_config.cairn.timeout = 60
        mock_config.cairn.limits_preset = "default"
        mock_config.cairn.limits_override = {}

        mock_emitter = MagicMock()

        with patch("remora.kernel_runner.GrailBackend"):
            with patch("remora.kernel_runner.AgentKernel") as MockKernel:
                mock_kernel = AsyncMock()
                mock_result = MagicMock()
                mock_result.termination_reason = "termination_tool"
                mock_result.final_tool_result = MagicMock()
                mock_result.final_tool_result.name = "submit_result"
                mock_result.final_tool_result.output = '{"status": "success", "summary": "Done"}'
                mock_kernel.run.return_value = mock_result
                mock_kernel.close = AsyncMock()
                MockKernel.return_value = mock_kernel

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
                    mock_bundle.build_initial_messages.return_value = []
                    mock_load.return_value = mock_bundle

                    runner = KernelRunner(
                        node=mock_node,
                        ctx=mock_ctx,
                        config=mock_config,
                        bundle_path=sample_bundle,
                        event_emitter=mock_emitter,
                    )

                    result = await runner.run()

                    assert result.status == AgentStatus.SUCCESS
                    assert result.summary == "Done"
                    mock_kernel.run.assert_called_once()
