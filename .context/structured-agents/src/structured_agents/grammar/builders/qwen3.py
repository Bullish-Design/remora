"""Grammar builder for Qwen3 tool calling format."""

from __future__ import annotations

from structured_agents.grammar.artifacts import (
    EBNFGrammar,
    GrammarArtifact,
    JsonSchemaGrammar,
    StructuralTagGrammar,
)
from structured_agents.grammar.config import GrammarConfig
from structured_agents.grammar.utils import escape_ebnf_string
from structured_agents.types import ToolSchema

from xgrammar import StructuralTag
from xgrammar.structural_tag import (
    GrammarFormat,
    OrFormat,
    SequenceFormat,
    TagFormat,
)


class Qwen3GrammarBuilder:
    """Grammar builder for Qwen3 models."""

    def supports_mode(self, mode: str) -> bool:
        return mode in ("ebnf", "structural_tag", "json_schema")

    def build(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> GrammarArtifact | None:
        if not tools:
            return None

        if config.mode == "json_schema":
            return self._build_json_schema(tools, config)
        if config.mode == "ebnf":
            return self._build_ebnf(tools, config)

        return self._build_structural_tag(tools, config)

    def _build_ebnf(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> EBNFGrammar:
        """Build EBNF grammar for Qwen3 format."""
        tool_names = [escape_ebnf_string(tool.name) for tool in tools]
        tool_alts = " | ".join(f'"{name}"' for name in tool_names)

        if config.allow_parallel_calls:
            root_rule = "root ::= tool_call+"
        else:
            root_rule = "root ::= tool_call"

        grammar = "\n".join(
            [
                root_rule,
                "",
                'tool_call ::= "<function=" tool_name ">" parameters "</function>"',
                "",
                f"tool_name ::= {tool_alts}",
                "",
                "parameters ::= (parameter)*",
                'parameter ::= "<parameter=" param_name ">" param_value "</parameter>"',
                "param_name ::= [a-zA-Z_][a-zA-Z0-9_]*",
                "param_value ::= [^<]+",
            ]
        )

        return EBNFGrammar(grammar=grammar)

    def _build_structural_tag(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> StructuralTagGrammar:
        """Build structural tag grammar for Qwen3 format.

        Qwen3 format:
        <tool_call>
        <function=tool_name>
        <parameter=name>value</parameter>
        </function>
        </tool_call>
        """
        tool_tags = []
        for tool in tools:
            args_grammar = self._build_args_grammar_for_tool(tool, config)
            tool_tags.append(
                TagFormat(
                    begin=f"<function={tool.name}>",
                    content=GrammarFormat(grammar=args_grammar),
                    end="</function>",
                )
            )

        if len(tool_tags) == 1:
            tag_choice = tool_tags[0]
        else:
            tag_choice = OrFormat(elements=tool_tags)

        if config.allow_parallel_calls:
            format_spec = SequenceFormat(
                elements=[tag_choice],
            )
        else:
            format_spec = tag_choice

        structural_tag = StructuralTag(format=format_spec)
        return StructuralTagGrammar(tag=structural_tag)

    def _build_args_grammar_for_tool(
        self, tool: ToolSchema, config: GrammarConfig
    ) -> str:
        """Build argument grammar for a specific tool."""
        return "(<parameter=[^>]+>[^<]*</parameter>)*"

    def _build_json_schema(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> JsonSchemaGrammar:
        """Build JSON schema grammar for Qwen3 format."""
        tool_choices = []
        for tool in tools:
            tool_choices.append(
                {
                    "type": "object",
                    "properties": {
                        "name": {"const": tool.name},
                        "arguments": tool.parameters,
                    },
                    "required": ["name", "arguments"],
                }
            )

        if len(tool_choices) > 1:
            schema = {
                "type": "array",
                "items": {"anyOf": tool_choices},
            }
        else:
            schema = tool_choices[0]

        return JsonSchemaGrammar(schema=schema)
