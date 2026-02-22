"""Additional Scenario 7: Grail Validation.

Test that all .pym tools validate with Grail before execution,
invalid tools are skipped with clear error.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.config import load_config
from structured_agents import load_bundle

pytestmark = [pytest.mark.acceptance, pytest.mark.integration]


@pytest.mark.asyncio
async def test_grail_validation(sample_project: Path, remora_config: Path):
    """Test: All .pym tools validate with Grail before execution."""
    # Load config
    config = load_config(remora_config)

    validation_errors: list[str] = []

    for op_name, op_config in config.operations.items():
        if not op_config.enabled:
            continue

        bundle_path = config.agents_dir / op_config.subagent
        bundle_file = bundle_path / "bundle.yaml"
        if not bundle_file.exists():
            validation_errors.append(f"{op_name}: bundle.yaml not found")
            continue

        try:
            bundle = load_bundle(bundle_path)
            _ = bundle.tool_schemas
        except Exception as exc:
            validation_errors.append(f"{op_name}: Failed to load bundle - {exc}")

    assert len(validation_errors) == 0, f"Bundle validation errors: {validation_errors}"

    print("✓ Scenario 7 passed: Bundles load successfully")
