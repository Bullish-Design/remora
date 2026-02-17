"""Subagent definition parsing for Remora."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import warnings

import jinja2
import yaml
from pydantic import BaseModel, Field, field_validator

from remora.discovery import CSTNode
from remora.errors import AGENT_001


class SubagentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_path(base: Path, relative: str | Path) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (base / path).resolve()


class ToolDefinition(BaseModel):
    name: str
    pym: Path
    description: str
    parameters: dict[str, Any]
    context_providers: list[Path] = Field(default_factory=list)

    @field_validator("parameters")
    @classmethod
    def validate_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Tool parameters must be a JSON schema object.")
        if value.get("type") != "object":
            raise ValueError("Tool parameters must define type: object.")
        if value.get("additionalProperties") is not False:
            warnings.warn(
                "Tool parameters should set additionalProperties: false for strict mode.",
                stacklevel=2,
            )
        return value


class InitialContext(BaseModel):
    system_prompt: str
    node_context: str

    def render(self, node: CSTNode) -> str:
        template = jinja2.Template(self.node_context)
        return template.render(
            node_text=node.text,
            node_name=node.name,
            node_type=node.node_type,
            file_path=str(node.file_path),
        )


class SubagentDefinition(BaseModel):
    name: str
    model_id: str | None = None
    max_turns: int = 20
    initial_context: InitialContext
    tools: list[ToolDefinition]

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "strict": True,
                },
            }
            for tool in self.tools
        ]

    @property
    def tools_by_name(self) -> dict[str, ToolDefinition]:
        return {tool.name: tool for tool in self.tools}


def load_subagent_definition(path: Path, agents_dir: Path) -> SubagentDefinition:
    resolved_path = resolve_path(agents_dir, path)
    data = _load_yaml(resolved_path)
    resolved = _resolve_paths(data, agents_dir)
    definition = SubagentDefinition.model_validate(resolved)
    _validate_submit_result(definition, resolved_path)
    _warn_missing_paths(definition)
    return definition


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SubagentError(AGENT_001, f"Failed to read subagent definition: {path}") from exc
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise SubagentError(AGENT_001, f"Invalid YAML in subagent definition: {path}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SubagentError(AGENT_001, f"Subagent definition must be a mapping: {path}")
    return data


def _resolve_paths(data: dict[str, Any], agents_dir: Path) -> dict[str, Any]:
    resolved: dict[str, Any] = dict(data)
    tools_data = []
    for tool in resolved.get("tools", []) or []:
        tool_copy = dict(tool)
        if "pym" in tool_copy:
            tool_copy["pym"] = resolve_path(agents_dir, tool_copy["pym"])
        context_providers = tool_copy.get("context_providers") or []
        tool_copy["context_providers"] = [resolve_path(agents_dir, provider) for provider in context_providers]
        tools_data.append(tool_copy)
    if tools_data:
        resolved["tools"] = tools_data
    return resolved


def _validate_submit_result(definition: SubagentDefinition, path: Path) -> None:
    submit_tools = [tool for tool in definition.tools if tool.name == "submit_result"]
    if len(submit_tools) != 1:
        raise SubagentError(
            AGENT_001,
            f"Subagent definition must include exactly one submit_result tool: {path}",
        )


def _warn_missing_paths(definition: SubagentDefinition) -> None:
    for tool in definition.tools:
        if not tool.pym.exists():
            warnings.warn(f"Tool script not found: {tool.pym}", stacklevel=2)
        for provider in tool.context_providers:
            if not provider.exists():
                warnings.warn(f"Context provider not found: {provider}", stacklevel=2)
