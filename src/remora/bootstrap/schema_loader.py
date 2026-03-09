"""Bootstrap schema.yaml loader."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from remora.core.agents.cairn_externals import CairnExternals


# Fallback default schema used when workspace schema.yaml is missing and the
# filesystem default cannot be loaded. The authoritative default lives in
# bootstrap/agents/DEFAULT_SCHEMA.yaml and is preferred when available.
DEFAULT_SCHEMA_YAML = """
version: "1"
name: bootstrap_default

system: |
  You are a Remora bootstrap agent. Your workspace is empty.

  Read your activation context. Decide what you are responsible for.
  Then do the following before ending your turn:
    1. Call write_file("role.md", <your role description>).
    2. Call write_file("notes.md", <initial notes about this node>).
    3. Call write_file("schema.yaml", <your turn definition for future activations>).

  When you have completed these three writes, output: DONE

context: []

tools:
  - read_file
  - write_file

max_turns: 5
termination: "DONE"
""".strip()


class ContextStep(BaseModel):
    name: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class SubscriptionSpec(BaseModel):
    event_type: str
    node_id: str | None = None


class TurnSchema(BaseModel):
    version: str = "1"
    name: str = "unnamed"
    system: str = ""
    context: list[ContextStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    subscriptions: list[SubscriptionSpec] = Field(default_factory=list)
    max_turns: int = 5
    termination: str = "DONE"
    extends: str | None = None


def _load_yaml(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    if isinstance(data, dict):
        return data
    return {}


def _merge_schemas(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge where child overrides base and list fields append."""
    merged = dict(base)
    for key, value in child.items():
        if key == "extends":
            continue
        if key in ("context", "tools", "subscriptions") and key in merged:
            merged[key] = (merged[key] or []) + (value or [])
        else:
            merged[key] = value
    return merged


async def load_schema(
    cairn_externals: CairnExternals,
    *,
    system_agents_dir: Path | None = None,
) -> TurnSchema:
    """Load schema.yaml from the agent's Cairn workspace."""
    content = await cairn_externals.read_file("schema.yaml")

    if not content:
        if system_agents_dir is not None:
            default_path = system_agents_dir / "DEFAULT_SCHEMA.yaml"
            if default_path.exists():
                return TurnSchema.model_validate(
                    _load_yaml(default_path.read_text(encoding="utf-8"))
                )
        return TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))

    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    child_data = _load_yaml(content)

    extends = child_data.get("extends")
    if extends and system_agents_dir:
        base_path = system_agents_dir / f"{extends}.yaml"
        if base_path.exists():
            base_data = _load_yaml(base_path.read_text(encoding="utf-8"))
            child_data = _merge_schemas(base_data, child_data)

    return TurnSchema.model_validate(child_data)


def resolve_context_vars(text: str, context_values: dict[str, str]) -> str:
    """Resolve {{name}} references from computed context values."""

    def replacer(match: re.Match[str]) -> str:
        return context_values.get(match.group(1), "")

    return re.sub(r"\{\{([^}]+)\}\}", replacer, text)


__all__ = [
    "ContextStep",
    "SubscriptionSpec",
    "TurnSchema",
    "DEFAULT_SCHEMA_YAML",
    "load_schema",
    "resolve_context_vars",
]
