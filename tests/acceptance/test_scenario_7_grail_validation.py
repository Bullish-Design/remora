"""Additional Scenario 7: Grail Validation.

Test that all .pym tools validate with Grail before execution,
invalid tools are skipped with clear error.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.analyzer import RemoraAnalyzer
from remora.cairn import CairnCLIClient
from remora.config import load_config
from remora.subagent import load_subagent_definition

pytestmark = pytest.mark.acceptance


@pytest.mark.asyncio
async def test_grail_validation(sample_project: Path, remora_config: Path):
    """Test: All .pym tools validate with Grail before execution."""
    # Load config
    config = load_config(remora_config)

    # Check that all configured subagents pass Grail validation
    validation_errors = []

    for op_name, op_config in config.operations.items():
        if not op_config.enabled:
            continue

        yaml_path = config.agents_dir / op_config.subagent
        if not yaml_path.exists():
            validation_errors.append(f"{op_name}: Subagent YAML not found")
            continue

        try:
            definition = load_subagent_definition(yaml_path, config.agents_dir)
            grail_summary = definition.grail_summary

            if not grail_summary.get("valid", False):
                validation_errors.append(f"{op_name}: Grail validation failed - {grail_summary.get('warnings', [])}")
        except Exception as exc:
            validation_errors.append(f"{op_name}: Failed to load - {exc}")

    # All enabled operations should pass Grail validation
    assert len(validation_errors) == 0, f"Grail validation errors: {validation_errors}"

    print("✓ Scenario 7 passed: Grail Validation (all tools valid)")
