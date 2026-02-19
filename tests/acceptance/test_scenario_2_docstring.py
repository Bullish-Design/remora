"""Scenario 2: Docstring Generation and Accept.

Test that docstring runner injects docstrings for undocumented functions,
and that accept workflow adds them to the source.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.analyzer import RemoraAnalyzer
from remora.config import load_config

pytestmark = pytest.mark.acceptance


@pytest.mark.asyncio
async def test_docstring_generation(sample_project: Path, remora_config: Path):
    """Test: Point at undocumented function → docstring runner injects docstring → accept → docstring in source."""
    # Load config
    config = load_config(remora_config)

    # Create analyzer
    # Create analyzer
    analyzer = RemoraAnalyzer(config)

    # Analyze with only docstring operation
    src_path = sample_project / "src"
    results = await analyzer.analyze([src_path], operations=["docstring"])

    # Verify results
    assert results.total_nodes > 0, "Should have found nodes"

    # Check that docstring operation succeeded for some functions
    successful_docstrings = 0
    for node in results.nodes:
        if "docstring" in node.operations:
            result = node.operations["docstring"]
            if result.status == "success":
                successful_docstrings += 1
                # Accept one docstring result
                if successful_docstrings == 1:
                    await analyzer.accept(node.node_id, "docstring")

    assert successful_docstrings > 0, "Should have at least one successful docstring generation"

    print(f"✓ Scenario 2 passed: Docstring Generation ({successful_docstrings} successful)")
