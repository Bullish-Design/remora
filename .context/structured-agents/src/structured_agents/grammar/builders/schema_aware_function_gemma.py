from __future__ import annotations

import re
from typing import Any

from structured_agents.grammar.artifacts import EBNFGrammar, GrammarArtifact
from structured_agents.grammar.config import GrammarConfig
from structured_agents.grammar.utils import escape_ebnf_string
from structured_agents.types import ToolSchema


class FunctionGemmaSchemaGrammarBuilder:
    """Schema-aware grammar builder for FunctionGemma models."""

    def supports_mode(self, mode: str) -> bool:
        return mode == "json_schema"

    def build(self, tools: list[ToolSchema], config: GrammarConfig) -> GrammarArtifact:
        if not tools:
            return None

        emitter = _SchemaGrammarEmitter()
        tool_rules: list[str] = []
        rule_lines: list[str] = []

        for tool in tools:
            args_rule_name = emitter.build_args_rule(tool.name, tool.parameters)
            tool_rule_name = emitter.next_rule_name(f"tool_call_{tool.name}")
            tool_rules.append(tool_rule_name)
            tool_name = escape_ebnf_string(tool.name)
            rule_lines.append(
                f'{tool_rule_name} ::= "<start_function_call>" "call:" "{tool_name}" "{{" {args_rule_name} "}}" "<end_function_call>"'
            )

        if config.allow_parallel_calls:
            root_rule = "root ::= function_call+"
        else:
            root_rule = "root ::= function_call"

        grammar = "\n".join(
            [
                root_rule,
                "",
                "function_call ::= " + " | ".join(tool_rules),
                "",
                *emitter.rules,
                *rule_lines,
                "",
                *emitter.base_rules(),
            ]
        )

        return EBNFGrammar(grammar=grammar)


class _SchemaGrammarEmitter:
    def __init__(self) -> None:
        self._rules: list[str] = []
        self._counter = 0

    @property
    def rules(self) -> list[str]:
        return self._rules

    def next_rule_name(self, hint: str) -> str:
        self._counter += 1
        cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", hint)
        return f"{cleaned}_{self._counter}"

    def build_args_rule(self, tool_name: str, schema: dict[str, Any]) -> str:
        if schema.get("type") != "object" and "properties" not in schema:
            rule_name = self.next_rule_name(f"{tool_name}_args")
            self._rules.append(f"{rule_name} ::= json_value")
            return rule_name

        return self._build_object_body_rule(schema, f"{tool_name}_args")

    def _build_object_body_rule(self, schema: dict[str, Any], hint: str) -> str:
        properties = schema.get("properties", {})
        required = [name for name in schema.get("required", []) if name in properties]
        optional = [name for name in properties if name not in required]

        body_rule_name = self.next_rule_name(hint)
        pair_rules: list[str] = []

        for name in required + optional:
            pair_rule = self.next_rule_name(f"pair_{name}")
            pair_rules.append(pair_rule)
            value_rule = self._build_schema_rule(properties[name], name)
            escaped_name = escape_ebnf_string(name)
            self._rules.append(
                f'{pair_rule} ::= "\\"{escaped_name}\\"" ":" {value_rule}'
            )

        if not pair_rules:
            self._rules.append(f'{body_rule_name} ::= ""')
            return body_rule_name

        required_pairs = pair_rules[: len(required)]
        optional_pairs = pair_rules[len(required) :]

        if required_pairs:
            sequence = self._sequence(required_pairs)
            optional_segments = "".join(f' ("," {pair})?' for pair in optional_pairs)
            self._rules.append(f"{body_rule_name} ::= {sequence}{optional_segments}")
            return body_rule_name

        alternatives = []
        for index, pair in enumerate(optional_pairs):
            tail = "".join(
                f' ("," {next_pair})?' for next_pair in optional_pairs[index + 1 :]
            )
            alternatives.append(f"{pair}{tail}")

        alternatives.append('""')
        self._rules.append(f"{body_rule_name} ::= " + " | ".join(alternatives))
        return body_rule_name

    def _sequence(self, rules: list[str]) -> str:
        if not rules:
            return ""
        sequence = rules[0]
        for rule in rules[1:]:
            sequence += f' "," {rule}'
        return sequence

    def _build_schema_rule(self, schema: dict[str, Any], hint: str) -> str:
        if "enum" in schema:
            return self._build_enum_rule(schema["enum"], hint)

        schema_type = schema.get("type")
        if schema_type == "string":
            return "json_string"
        if schema_type == "integer":
            return "json_integer"
        if schema_type == "number":
            return "json_number"
        if schema_type == "boolean":
            return "json_boolean"
        if schema_type == "null":
            return "json_null"
        if schema_type == "array":
            return self._build_array_rule(schema, hint)
        if schema_type == "object":
            return self._build_object_rule(schema, hint)

        return "json_value"

    def _build_enum_rule(self, values: list[Any], hint: str) -> str:
        rule_name = self.next_rule_name(f"enum_{hint}")
        literals: list[str] = []
        for value in values:
            if isinstance(value, str):
                literals.append(f'"{escape_ebnf_string(value)}"')
            elif value is True:
                literals.append('"true"')
            elif value is False:
                literals.append('"false"')
            elif value is None:
                literals.append('"null"')
            else:
                literals.append(f'"{value}"')
        self._rules.append(f"{rule_name} ::= " + " | ".join(literals))
        return rule_name

    def _build_array_rule(self, schema: dict[str, Any], hint: str) -> str:
        rule_name = self.next_rule_name(f"array_{hint}")
        items_schema = schema.get("items", {})
        item_rule = self._build_schema_rule(items_schema, f"{hint}_item")
        self._rules.append(f'{rule_name} ::= "[" ({item_rule} ("," {item_rule})*)? "]"')
        return rule_name

    def _build_object_rule(self, schema: dict[str, Any], hint: str) -> str:
        body_rule = self._build_object_body_rule(schema, f"{hint}_body")
        rule_name = self.next_rule_name(f"object_{hint}")
        self._rules.append(f'{rule_name} ::= "{{" {body_rule} "}}"')
        return rule_name

    def base_rules(self) -> list[str]:
        return [
            'json_string ::= "\\"" [^"]* "\\""',
            'json_number ::= "-"? [0-9]+ ("." [0-9]+)?',
            'json_integer ::= "-"? [0-9]+',
            'json_boolean ::= "true" | "false"',
            'json_null ::= "null"',
            "json_value ::= json_string | json_number | json_boolean | json_null",
        ]
