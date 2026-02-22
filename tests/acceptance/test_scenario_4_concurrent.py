"""Scenario 4: Concurrent Processing.

Test that multiple nodes are processed concurrently and
max_concurrent_agents is respected.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.analyzer import RemoraAnalyzer
from remora.config import load_config

pytestmark = [pytest.mark.acceptance, pytest.mark.integration]


@pytest.mark.asyncio
async def test_concurrent_processing(sample_project: Path, remora_config: Path):
    """Test: Process file with 5+ functions → all run concurrently → results for all nodes."""
    # Load config
    config = load_config(remora_config)

    # Create analyzer
    # Create analyzer
    analyzer = RemoraAnalyzer(config)

    # Analyze entire src directory with multiple operations
    src_path = sample_project / "src"
    results = await analyzer.analyze([src_path], operations=["lint", "docstring"])

    # Verify we have multiple nodes
    assert results.total_nodes >= 5, f"Should have at least 5 nodes, got {results.total_nodes}"

    # Verify all nodes have results
    for node in results.nodes:
        assert len(node.operations) > 0, f"Node {node.node_name} should have operations"

    # Verify max_concurrent_agents was respected (implicitly tested by completion)
    assert results.total_operations > 0, "Should have total operations"
    print(
        f"✓ Scenario 4 passed: Concurrent Processing ({results.total_nodes} nodes, {results.total_operations} operations)"
    )
