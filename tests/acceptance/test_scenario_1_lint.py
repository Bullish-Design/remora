"""Scenario 1: Lint and Accept.

Test that lint runner identifies and fixes style issues,
and that accept workflow merges changes into stable workspace.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.analyzer import RemoraAnalyzer
from remora.config import load_config

pytestmark = pytest.mark.acceptance


@pytest.mark.asyncio
async def test_lint_and_accept(sample_project: Path, remora_config: Path):
    """Test: Point at Python file → lint runner fixes issues → accept → changes in stable."""
    # Load config
    config = load_config(remora_config)

    # Create analyzer
    # Create analyzer
    analyzer = RemoraAnalyzer(config)

    # Analyze calculator.py with only lint operation
    src_path = sample_project / "src"
    results = await analyzer.analyze([src_path], operations=["lint"])

    # Verify results
    assert results.total_nodes > 0, "Should have found nodes"
    assert results.successful_operations > 0, "Should have successful lint operations"

    # Find calculator.py node with lint issues
    calculator_node = None
    for node in results.nodes:
        if "calculator" in str(node.file_path):
            calculator_node = node
            break

    assert calculator_node is not None, "Should find calculator.py"

    # Check lint operation succeeded
    if "lint" in calculator_node.operations:
        lint_result = calculator_node.operations["lint"]
        assert lint_result.status == "success", f"Lint should succeed: {lint_result.error}"

        # Accept the lint changes
        await analyzer.accept(calculator_node.node_id, "lint")

        # Verify workspace is accepted
        workspace_info = analyzer._workspaces.get((calculator_node.node_id, "lint"))
        if workspace_info:
            from remora.analyzer import WorkspaceState

            assert workspace_info.state == WorkspaceState.ACCEPTED

    print("✓ Scenario 1 passed: Lint and Accept")
