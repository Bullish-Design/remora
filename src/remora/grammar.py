"""FunctionGemma grammar builder for vLLM structured outputs."""

from __future__ import annotations

from typing import Any


def build_functiongemma_grammar(tools: list[dict[str, Any]]) -> str:
    """Build a strict JSON EBNF grammar for FunctionGemma tool calls.

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
    quote = '"\\""'

    return "\n".join(
        [
            'root ::= ws? "<start_function_call>" "call:" tool_name ws? obj "<end_function_call>" ws?',
            "",
            f"tool_name ::= {tool_alternatives}",
            "",
            'obj ::= "{" ws? members? ws? "}"',
            'members ::= member (ws? "," ws? member)*',
            'member ::= string ws? ":" ws? value',
            "",
            'value ::= string | number | boolean | "null" | obj | array',
            'array ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"',
            "",
            f"string ::= {quote} str_char* {quote}",
            'str_char ::= [^"\\\\]',
            "",
            'number ::= "-"? int frac? exp?',
            'int    ::= "0" | [1-9] [0-9]*',
            'frac   ::= "." [0-9]+',
            'exp    ::= ("e"|"E") ("+"|"-")? [0-9]+',
            "",
            'boolean ::= "true" | "false"',
            "",
            "ws ::= [ \t\r\n]+",
            "",
        ]
    )
