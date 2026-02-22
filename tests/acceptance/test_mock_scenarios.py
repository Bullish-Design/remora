"""Acceptance tests that use mock vLLM server (CI-friendly)."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.analyzer import RemoraAnalyzer
from remora.config import load_config
from remora.constants import TERMINATION_TOOL

pytestmark = [pytest.mark.asyncio, pytest.mark.acceptance_mock]


async def test_lint_scenario_with_mock(
    sample_project: Path,
    remora_config: Path,
    mock_vllm_server,
) -> None:
    """Test lint workflow with mock vLLM server."""
    server, url = mock_vllm_server

    server.add_tool_call_response(
        "run_linter",
        {"check_only": True, "target_file": "src/calculator.py"},
        pattern="lint",
    )
    server.add_tool_call_response(
        "submit_result",
        {
            "summary": "Linting complete",
            "issues_fixed": 0,
            "issues_remaining": 0,
            "changed_files": ["src/calculator.py"],
        },
        pattern=".*",
    )

    config = load_config(remora_config)
    config.server.base_url = url
    config.server.default_adapter = server.default_model

    analyzer = RemoraAnalyzer(config)
    results = await analyzer.analyze(
        [sample_project / "src"],
        operations=["lint"],
    )

    assert results.total_nodes > 0
    assert results.successful_operations > 0


async def test_docstring_scenario_with_mock(
    sample_project: Path,
    remora_config: Path,
    mock_vllm_server,
) -> None:
    """Test docstring generation with mock vLLM server."""
    server, url = mock_vllm_server

    server.add_tool_call_response(
        "read_current_docstring",
        {},
        pattern="docstring",
    )
    server.add_tool_call_response(
        "write_docstring",
        {"docstring": "A sample function.", "style": "google"},
        pattern=".*",
    )
    server.add_tool_call_response(
        TERMINATION_TOOL,
        {"summary": "Docstring written", "action": "updated", "changed_files": []},
    )

    config = load_config(remora_config)
    config.server.base_url = url
    config.server.default_adapter = server.default_model

    analyzer = RemoraAnalyzer(config)
    results = await analyzer.analyze(
        [sample_project / "src"],
        operations=["docstring"],
    )

    assert results.total_nodes > 0
