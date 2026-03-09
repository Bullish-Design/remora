from __future__ import annotations

from pathlib import Path

import yaml

from remora.bootstrap.schema_loader import TurnSchema

AGENTS_DIR = Path("bootstrap/agents")


def test_bootstrap_agent_schema_files_exist() -> None:
    expected = {
        "DEFAULT_SCHEMA.yaml",
        "base_code_agent.yaml",
        "coordinator.yaml",
    }
    files = {path.name for path in AGENTS_DIR.glob("*.yaml")}
    assert files >= expected


def test_bootstrap_agent_schema_files_validate() -> None:
    for schema_file in AGENTS_DIR.glob("*.yaml"):
        data = yaml.safe_load(schema_file.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        schema = TurnSchema.model_validate(data)
        assert schema.termination == "DONE"


def test_coordinator_schema_subscribes_to_bootstrap_events() -> None:
    data = yaml.safe_load((AGENTS_DIR / "coordinator.yaml").read_text(encoding="utf-8"))
    schema = TurnSchema.model_validate(data)

    event_types = {spec.event_type for spec in schema.subscriptions}
    assert "AgentNeededEvent" in event_types
    assert "ToolSynthesizedEvent" in event_types
