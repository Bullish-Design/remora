"""FunctionGemma grammar builder for vLLM structured outputs."""

from __future__ import annotations

from typing import Any


def build_functiongemma_grammar(tools: list[dict[str, Any]]) -> str:
    """Build a permissive EBNF grammar for FunctionGemma tool calls.

    Args:
        tools: OpenAI-format tool schemas

    Returns:
        EBNF grammar string for vLLM structured outputs
    """
    tool_names = [
        tool["function"]["name"]
        for tool in tools
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict) and "name" in tool["function"]
    ]
    if not tool_names:
        raise ValueError("No function tools found in schema")

    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    tool_alternatives = " | ".join(f'"{esc(name)}"' for name in tool_names)

    # Strict grammar per XGRAMMAR_REFACTOR_PLAN.md - no whitespace between call: and tool_name
    return "\n".join(
        [
            'root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"',
            "",
            f"tool_name ::= {tool_alternatives}",
            "",
            "arg_body ::= arg_char*",
            "arg_char ::= [^}]",
            "",
        ]
    )
