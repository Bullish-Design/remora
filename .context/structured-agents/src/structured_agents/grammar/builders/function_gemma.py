from __future__ import annotations

from structured_agents.grammar.artifacts import (
    EBNFGrammar,
    GrammarArtifact,
    StructuralTagGrammar,
)
from structured_agents.grammar.config import GrammarConfig
from structured_agents.grammar.utils import escape_ebnf_string
from structured_agents.types import ToolSchema

from xgrammar import StructuralTag
from xgrammar.structural_tag import GrammarFormat, OrFormat, SequenceFormat, TagFormat


class FunctionGemmaGrammarBuilder:
    """Grammar builder for FunctionGemma models."""

    def supports_mode(self, mode: str) -> bool:
        return mode in ("ebnf", "structural_tag")

    def build(self, tools: list[ToolSchema], config: GrammarConfig) -> GrammarArtifact:
        if not tools:
            return None

        if config.mode == "structural_tag":
            return self._build_structural_tag(tools, config)

        return self._build_ebnf(tools, config)

    def _build_ebnf(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> EBNFGrammar:
        """Build EBNF grammar for FunctionGemma format."""
        tool_names = [escape_ebnf_string(tool.name) for tool in tools]
        tool_alts = " | ".join(f'"{name}"' for name in tool_names)

        if config.allow_parallel_calls:
            root_rule = "root ::= function_call+"
        else:
            root_rule = "root ::= function_call"

        if config.args_format == "escaped_strings":
            arg_body = self._escaped_string_args_grammar()
        elif config.args_format == "json":
            arg_body = self._json_args_grammar()
        else:
            arg_body = "arg_body ::= [^}]*"

        grammar = "\n".join(
            [
                root_rule,
                "",
                'function_call ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"',
                "",
                f"tool_name ::= {tool_alts}",
                "",
                arg_body,
            ]
        )

        return EBNFGrammar(grammar=grammar)

    def _build_structural_tag(
        self, tools: list[ToolSchema], config: GrammarConfig
    ) -> StructuralTagGrammar:
        """Build structural tag for FunctionGemma format."""
        tool_formats = []

        for tool in tools:
            args_grammar = self._build_args_grammar_for_tool(tool, config)

            tool_formats.append(
                TagFormat(
                    begin=f"<start_function_call>call:{tool.name}{{",
                    content=GrammarFormat(grammar=args_grammar),
                    end="}<end_function_call>",
                )
            )

        if len(tool_formats) == 1:
            format_spec = tool_formats[0]
        else:
            format_spec = OrFormat(elements=tool_formats)

        if config.allow_parallel_calls:
            format_spec = SequenceFormat(elements=[format_spec])

        tag = StructuralTag(format=format_spec)

        return StructuralTagGrammar(tag=tag)

    def _build_args_grammar_for_tool(
        self, tool: ToolSchema, config: GrammarConfig
    ) -> str:
        """Build argument grammar for a specific tool."""
        return "[^}]*"

    def _escaped_string_args_grammar(self) -> str:
        """Grammar supporting FunctionGemma <escape> delimiters."""
        return "\n".join(
            [
                'arg_body ::= (arg_pair ("," arg_pair)*)?',
                'arg_pair ::= arg_name ":" arg_value',
                "arg_name ::= [a-zA-Z_][a-zA-Z0-9_]*",
                'arg_value ::= escaped_string | number | "true" | "false" | "null"',
                'escaped_string ::= "<escape>" [^<]* "<escape>"',
                'number ::= "-"? [0-9]+ ("." [0-9]+)?',
            ]
        )

    def _json_args_grammar(self) -> str:
        """Grammar for JSON-formatted arguments."""
        return "\n".join(
            [
                'arg_body ::= (pair ("," pair)*)?',
                'pair ::= string ":" value',
                'string ::= "\\"" [^\\"]* "\\""',
                'value ::= string | number | object | array | "true" | "false" | "null"',
                'object ::= "{" (pair ("," pair)*)? "}"',
                'array ::= "[" (value ("," value)*)? "]"',
                'number ::= "-"? [0-9]+ ("." [0-9]+)?',
            ]
        )
