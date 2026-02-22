"""Subagent definition parsing for Remora."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import warnings

import jinja2
import yaml
from pydantic import BaseModel, Field, PrivateAttr

from remora.discovery import CSTNode
from remora.errors import AGENT_001
from remora.tool_registry import GrailToolRegistry, ToolRegistryError

SUBMIT_RESULT_TOOL = "submit_result"


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
    pym: Path
    tool_name: str | None = None
    tool_description: str
    inputs_override: dict[str, dict[str, Any]] = Field(default_factory=dict)
    context_providers: list[Path] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.tool_name or self.pym.stem


class InitialContext(BaseModel):
    system_prompt: str
    node_context: str

    def render(self, node: CSTNode) -> str:
        template = jinja2.Template(self.node_context)
        return template.render(
            node_text=node.text,
            node_name=node.name,
            node_type=node.node_type.value,
            file_path=str(node.file_path),
        )


class SubagentDefinition(BaseModel):
    name: str
    model_id: str | None = None
    max_turns: int = 20
    initial_context: InitialContext
    tools: list[ToolDefinition]
    _tools_by_name: dict[str, ToolDefinition] = PrivateAttr(default_factory=dict)
    _tool_schemas: list[dict[str, Any]] = PrivateAttr(default_factory=list)
    _grail_summary: dict[str, Any] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _: Any) -> None:
        self._tools_by_name = {tool.name: tool for tool in self.tools}

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        return self._tool_schemas

    @property
    def tools_by_name(self) -> dict[str, ToolDefinition]:
        return self._tools_by_name

    @property
    def grail_summary(self) -> dict[str, Any]:
        return self._grail_summary


def load_subagent_definition(path: Path, agents_dir: Path) -> SubagentDefinition:
    resolved_path = resolve_path(agents_dir, path)
    data = _load_yaml(resolved_path)
    resolved = _resolve_paths(data, agents_dir)
    definition = SubagentDefinition.model_validate(resolved)
    _validate_submit_result(definition, resolved_path)
    _validate_tool_names(definition, resolved_path)
    _validate_jinja2_template(definition, resolved_path)
    _apply_tool_registry(definition, agents_dir, resolved_path)
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


def _apply_tool_registry(definition: SubagentDefinition, agents_dir: Path, path: Path) -> None:
    registry = GrailToolRegistry(agents_dir)
    try:
        catalog = registry.build_tool_catalog(definition.tools)
        definition._tool_schemas = catalog.schemas
        definition._grail_summary = catalog.grail_summary
    except ToolRegistryError as exc:
        raise SubagentError(exc.code, f"{path}: {exc}") from exc


def _validate_submit_result(definition: SubagentDefinition, path: Path) -> None:
    submit_tools = [tool for tool in definition.tools if tool.name == SUBMIT_RESULT_TOOL]
    if len(submit_tools) != 1:
        raise SubagentError(
            AGENT_001,
            f"Subagent definition must include exactly one {SUBMIT_RESULT_TOOL} tool: {path}",
        )


def _validate_tool_names(definition: SubagentDefinition, path: Path) -> None:
    seen: set[str] = set()
    for tool in definition.tools:
        if tool.name in seen:
            raise SubagentError(
                AGENT_001,
                f"Duplicate tool name '{tool.name}' in subagent definition: {path}",
            )
        seen.add(tool.name)


def _validate_jinja2_template(definition: SubagentDefinition, path: Path) -> None:
    env = jinja2.Environment()
    try:
        env.parse(definition.initial_context.node_context)
    except jinja2.TemplateSyntaxError as exc:
        raise SubagentError(
            AGENT_001,
            f"Invalid Jinja2 template in node_context of {path}: {exc}",
        ) from exc


def _warn_missing_paths(definition: SubagentDefinition) -> None:
    for tool in definition.tools:
        if not tool.pym.exists():
            raise SubagentError(AGENT_001, f"Tool script not found: {tool.pym}")
        for provider in tool.context_providers:
            if not provider.exists():
                raise SubagentError(AGENT_001, f"Context provider not found: {provider}")
