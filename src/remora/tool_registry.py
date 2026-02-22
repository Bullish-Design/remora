"""Grail-driven tool schema registry."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Protocol, Sequence
import warnings

import grail

from remora.errors import SubagentError

class ToolRegistryError(SubagentError):
    pass


class ToolConfig(Protocol):
    pym: Path
    tool_description: str
    inputs_override: dict[str, dict[str, Any]]

    @property
    def name(self) -> str: ...


@dataclass(slots=True)
class GrailInputSpec:
    name: str
    type: str | None
    required: bool
    default: Any | None


@dataclass(slots=True)
class GrailToolCatalog:
    schemas: list[dict[str, Any]]
    grail_summary: dict[str, Any]


@dataclass(slots=True)
class GrailToolRegistry:
    grail_root: Path
    strict: bool = True

    def build_tool_catalog(self, tools: Sequence[ToolConfig]) -> GrailToolCatalog:
        self.grail_root.mkdir(parents=True, exist_ok=True)
        schemas: list[dict[str, Any]] = []
        warnings_list: list[dict[str, Any]] = []
        for tool in tools:
            schema, tool_warnings = self._build_tool_schema(tool)
            schemas.append(schema)
            for warning in tool_warnings:
                warnings_list.append({"tool": tool.name, "message": warning})
        return GrailToolCatalog(
            schemas=schemas,
            grail_summary={"valid": True, "warnings": warnings_list},
        )

    def preflight_check_all(self, tools: Sequence[ToolConfig]) -> list[dict[str, Any]]:
        """Run GrailScript.check() on every tool's .pym file.

        Raises ToolRegistryError if any tool has check errors.
        Returns list of warning dicts for logging.
        """
        all_warnings: list[dict[str, Any]] = []
        errors: list[str] = []
        for tool in tools:
            try:
                script = grail.load(tool.pym, grail_dir=self.grail_root)
            except Exception as exc:
                errors.append(f"{tool.name}: failed to load: {exc}")
                continue
            check = script.check()
            if not check.valid:
                check_errors = [str(e) for e in (check.errors or [])]
                errors.append(f"{tool.name}: {'; '.join(check_errors)}")
            for warning in check.warnings or []:
                all_warnings.append({"tool": tool.name, "message": str(warning)})
        if errors:
            raise ToolRegistryError(
                f"Preflight check failed for {len(errors)} tool(s):\n" + "\n".join(errors),
            )
        return all_warnings

    def _build_tool_schema(self, tool: ToolConfig) -> tuple[dict[str, Any], list[str]]:
        try:
            script = grail.load(tool.pym, grail_dir=self.grail_root)
        except Exception as exc:
            raise ToolRegistryError(f"Failed to load Grail script {tool.pym}: {exc}") from exc
        check = script.check()
        if not check.valid or (self.strict and check.warnings):
            errors = [msg.message for msg in check.errors]
            if self.strict:
                errors.extend(msg.message for msg in check.warnings)
            joined = "; ".join(errors) if errors else "Unknown validation error"
            raise ToolRegistryError(
                f"Grail check failed for {tool.pym}: {joined}",
            )
        artifact_dir = self.grail_root / script.name
        inputs = _load_inputs(artifact_dir / "inputs.json", tool.pym)
        parameters = _build_parameters(inputs, tool.inputs_override, tool.pym)
        return (
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.tool_description,
                    "parameters": parameters,
                },
            },
            [msg.message for msg in check.warnings],
        )


def _load_inputs(path: Path, source_path: Path) -> list[GrailInputSpec]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ToolRegistryError(f"Missing Grail inputs.json for {source_path}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolRegistryError(f"Invalid inputs.json for {source_path}: {exc}") from exc
    raw_inputs = data.get("inputs")
    if not isinstance(raw_inputs, list):
        raise ToolRegistryError(f"Invalid inputs.json format for {source_path}: {path}")
    specs: list[GrailInputSpec] = []
    for item in raw_inputs:
        if not isinstance(item, dict):
            continue
        specs.append(
            GrailInputSpec(
                name=str(item.get("name")),
                type=item.get("type"),
                required=bool(item.get("required")),
                default=item.get("default"),
            )
        )
    return specs


def _build_parameters(
    inputs: list[GrailInputSpec],
    overrides: dict[str, dict[str, Any]],
    source_path: Path,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    overrides = overrides or {}

    inputs_by_name = {inp.name: inp for inp in inputs}
    for override_name in overrides:
        if override_name not in inputs_by_name:
            warnings.warn(
                f"inputs_override references unknown input '{override_name}' in {source_path}",
                stacklevel=2,
            )

    system_inputs = {
        "node_text",
        "target_file",
        "workspace_id",
        "node_text_input",
        "target_file_input",
    }

    for input_spec in inputs:
        base_schema, base_type = _schema_for_type(input_spec.type)
        override = overrides.get(input_spec.name, {})
        schema = dict(base_schema)

        if "type" in override and override["type"] != base_type:
            warnings.warn(
                f"inputs_override type mismatch for '{input_spec.name}' in {source_path}: "
                f"grail={base_type} override={override['type']}",
                stacklevel=2,
            )
        if "default" in override and override["default"] != input_spec.default:
            warnings.warn(
                f"inputs_override default mismatch for '{input_spec.name}' in {source_path}: "
                f"grail={input_spec.default} override={override['default']}",
                stacklevel=2,
            )
        if "required" in override and override["required"] != input_spec.required:
            warnings.warn(
                f"inputs_override required mismatch for '{input_spec.name}' in {source_path}: "
                f"grail={input_spec.required} override={override['required']}",
                stacklevel=2,
            )

        if "type" in override:
            schema["type"] = override["type"]
        if "description" in override:
            schema["description"] = override["description"]
        if "default" in override:
            schema["default"] = override["default"]
        elif input_spec.default is not None:
            schema["default"] = input_spec.default

        properties[input_spec.name] = schema
        required_flag = override.get("required", input_spec.required)
        if input_spec.name in system_inputs:
            required_flag = False
        if required_flag:
            required.append(input_spec.name)

    # NOTE: Do NOT include additionalProperties: false here.
    # vLLM has a bug where multiple tools with additionalProperties: false
    # causes a "Invalid JSON: EOF while parsing a list" validation error.
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        parameters["required"] = required
    return parameters


def _schema_for_type(type_name: str | None) -> tuple[dict[str, Any], str | None]:
    if not type_name:
        return {"type": "string"}, "string"
    parts = [part.strip() for part in type_name.split("|")]
    non_null = [part for part in parts if part not in {"None", "NoneType"}]
    if not non_null:
        return {"type": "null"}, "null"
    if len(non_null) == 1:
        schema, base_type = _schema_for_single_type(non_null[0])
        return schema, base_type
    schemas: list[dict[str, Any]] = []
    for part in non_null:
        schema, _ = _schema_for_single_type(part)
        schemas.append(schema)
    return {"anyOf": schemas}, None


def _schema_for_single_type(type_name: str) -> tuple[dict[str, Any], str | None]:
    normalized = type_name.strip()
    if normalized in {"int"}:
        return {"type": "integer"}, "integer"
    if normalized in {"float"}:
        return {"type": "number"}, "number"
    if normalized in {"bool", "boolean"}:
        return {"type": "boolean"}, "boolean"
    if normalized in {"str", "string"}:
        return {"type": "string"}, "string"
    if normalized.startswith("list") or normalized.startswith("set") or normalized.startswith("tuple"):
        inner_type = None
        if "[" in normalized and normalized.endswith("]"):
            inner_type = normalized[normalized.find("[") + 1 : -1].strip()
        if inner_type:
            item_schema, _ = _schema_for_single_type(inner_type)
        else:
            item_schema = {}
        return {"type": "array", "items": item_schema}, "array"
    if normalized.startswith("dict") or normalized.startswith("mapping"):
        return {"type": "object"}, "object"
    if normalized == "Any":
        return {}, None
    return {"type": "string"}, "string"
