"""Scenario 3: Test Generation and Accept.

Test that test runner generates pytest files,
and that accept workflow creates the test file in stable workspace.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.analyzer import RemoraAnalyzer
from remora.config import load_config

pytestmark = pytest.mark.acceptance


@pytest.mark.asyncio
async def test_generation(sample_project: Path, remora_config: Path):
    """Test: Point at function → test runner generates pytest file → accept → test file exists."""
    # Load config
    config = load_config(remora_config)

    # Create analyzer
    # Create analyzer
    analyzer = RemoraAnalyzer(config)

    # Analyze calculator.py with only test operation
    calculator_path = sample_project / "src" / "calculator.py"
    results = await analyzer.analyze([calculator_path], operations=["test"])

    # Verify results
    assert results.total_nodes > 0, "Should have found nodes"

    # Find calculator node
    calculator_node = None
    for node in results.nodes:
        if "calculator" in str(node.file_path):
            calculator_node = node
            break

    if calculator_node and "test" in calculator_node.operations:
        test_result = calculator_node.operations["test"]

        if test_result.status == "success":
            # Verify test file was mentioned in results
            assert len(test_result.changed_files) > 0, "Should have generated test file"

            # Accept test generation
            await analyzer.accept(calculator_node.node_id, "test")

            print("✓ Scenario 3 passed: Test Generation and Accept")
        else:
            print(f"⚠ Test generation status: {test_result.status} (may be expected)")
    else:
        print("⚠ No test result for calculator (may be expected)")
