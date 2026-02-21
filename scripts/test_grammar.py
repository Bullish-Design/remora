#!/usr/bin/env python3
"""Grammar test harness for validating EBNF grammars without vLLM.

This script allows rapid iteration on grammar development by:
1. Validating EBNF syntax locally
2. Testing grammars against sample inputs
3. Generating valid/invalid sample strings

Usage:
    python scripts/test_grammar.py                    # Run all tests
    python scripts/test_grammar.py --validate-only    # Just validate syntax
    python scripts/test_grammar.py --show-grammar     # Print generated grammar
    python scripts/test_grammar.py --test-input "..." # Test specific input
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

# Add src to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from remora.grammar import build_functiongemma_grammar

app = typer.Typer(help="Test EBNF grammars for FunctionGemma tool calling.")


# -----------------------------------------------------------------------------
# Sample tool schemas for testing
# -----------------------------------------------------------------------------

SAMPLE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "simple_tool",
            "description": "A simple tool for testing",
            "parameters": {
                "type": "object",
                "properties": {"payload": {"type": "string"}},
                "required": ["payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_result",
            "description": "Submit the final result",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "changed_files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "changed_files"],
            },
        },
    },
]

# Sample valid FunctionGemma outputs (should match grammar)
# Note: Strict grammar has no leading/trailing whitespace
VALID_SAMPLES = [
    '<start_function_call>call:simple_tool{payload:<escape>ping<escape>}<end_function_call>',
    '<start_function_call>call:submit_result{summary:<escape>Done<escape>, changed_files:[]}<end_function_call>',
    '<start_function_call>call:simple_tool{}<end_function_call>',
    '<start_function_call>call:simple_tool{test}<end_function_call>',
    '<start_function_call>call:simple_tool{payload: "test"}<end_function_call>',
    '<start_function_call>call:submit_result{summary:<escape>Success<escape>,changed_files:[<escape>file.py<escape>]}<end_function_call>',
]

# Sample invalid outputs (should NOT match grammar)
INVALID_SAMPLES = [
    "This is just plain text",
    "<start_function_call>call:unknown_tool{}<end_function_call>",  # Unknown tool
    "<start_function_call>call:simple_tool}<end_function_call>",  # Missing {
    "call:simple_tool{}",  # Missing wrapper tags
    "<start_function_call>simple_tool{}<end_function_call>",  # Missing call:
    "  <start_function_call>call:simple_tool{}<end_function_call>  ",  # Leading/trailing whitespace
]


# -----------------------------------------------------------------------------
# EBNF Validation
# -----------------------------------------------------------------------------


@dataclass
class EbnfValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]


def validate_ebnf_syntax(grammar: str) -> EbnfValidationResult:
    """Validate basic EBNF syntax without running it.

    This performs static analysis to catch common errors:
    - Missing production rules
    - Invalid character class syntax
    - Unbalanced quotes
    - Undefined rule references
    """
    errors: list[str] = []
    warnings: list[str] = []

    lines = grammar.strip().split("\n")
    defined_rules: set[str] = set()
    referenced_rules: set[str] = set()

    # Regex patterns for EBNF analysis
    rule_def_pattern = re.compile(r"^(\w+)\s*::=\s*(.+)$")
    rule_ref_pattern = re.compile(r"\b([a-z_][a-z0-9_]*)\b")
    string_literal_pattern = re.compile(r'"([^"\\]|\\.)*"')
    char_class_pattern = re.compile(r"\[([^\]]*)\]")

    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue

        # Check for rule definition
        match = rule_def_pattern.match(line)
        if match:
            rule_name = match.group(1)
            rule_body = match.group(2)
            defined_rules.add(rule_name)

            # Check for unbalanced quotes in rule body
            quote_count = rule_body.count('"') - rule_body.count('\\"')
            if quote_count % 2 != 0:
                errors.append(f"Line {line_num}: Unbalanced quotes in rule '{rule_name}'")

            # Check character class syntax
            for char_class_match in char_class_pattern.finditer(rule_body):
                char_class = char_class_match.group(1)
                # Check for common issues
                if char_class.startswith("^") and len(char_class) < 2:
                    errors.append(
                        f"Line {line_num}: Empty negated character class in '{rule_name}'"
                    )
                # Check for unescaped special characters that might be problematic
                if "\\\\" in char_class and "\\-" not in char_class:
                    warnings.append(
                        f"Line {line_num}: Possible escaping issue in character class of '{rule_name}'"
                    )

            # Collect rule references (excluding string literals)
            body_without_strings = string_literal_pattern.sub("", rule_body)
            body_without_char_classes = char_class_pattern.sub("", body_without_strings)
            for ref_match in rule_ref_pattern.finditer(body_without_char_classes):
                ref = ref_match.group(1)
                # Skip EBNF keywords and operators
                if ref not in {"true", "false", "null"}:
                    referenced_rules.add(ref)
        elif line and not line.startswith("#"):
            errors.append(f"Line {line_num}: Invalid syntax (not a rule definition): {line[:50]}")

    # Check for undefined rules
    undefined = referenced_rules - defined_rules
    for rule in undefined:
        # Skip single-character references (likely part of other tokens)
        if len(rule) > 1:
            errors.append(f"Undefined rule referenced: '{rule}'")

    # Check for unreferenced rules (except root)
    unreferenced = defined_rules - referenced_rules - {"root"}
    for rule in unreferenced:
        warnings.append(f"Rule '{rule}' is defined but never referenced")

    # Must have a root rule
    if "root" not in defined_rules:
        errors.append("Grammar must define a 'root' rule")

    return EbnfValidationResult(
        valid=len(errors) == 0, errors=errors, warnings=warnings
    )


# -----------------------------------------------------------------------------
# Pattern Matching (Simplified)
# -----------------------------------------------------------------------------


def build_regex_from_grammar(grammar: str, tools: list[dict[str, Any]]) -> re.Pattern[str]:
    """Build a simplified regex to test if strings might match the grammar.

    Note: This is NOT a full EBNF parser, just a quick validation tool.
    """
    tool_names = [
        t["function"]["name"]
        for t in tools
        if t.get("type") == "function" and "function" in t
    ]
    tool_pattern = "|".join(re.escape(name) for name in tool_names)

    # Build regex that approximates the strict grammar (no leading/trailing whitespace)
    pattern = (
        r"^"  # Start of string
        r"<start_function_call>"
        r"call:"
        rf"({tool_pattern})"  # Tool name (no whitespace allowed)
        r"\{"
        r"([^}]*)"  # Argument body (anything except })
        r"\}"
        r"<end_function_call>"
        r"$"  # End of string
    )
    return re.compile(pattern)


def test_string_against_grammar(
    text: str, grammar: str, tools: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    """Test if a string would match the grammar.

    Returns (matches, captured_tool_name_or_error).
    """
    try:
        regex = build_regex_from_grammar(grammar, tools)
        match = regex.match(text)
        if match:
            return True, match.group(1)
        return False, "No match"
    except Exception as e:
        return False, str(e)


# -----------------------------------------------------------------------------
# CLI Commands
# -----------------------------------------------------------------------------


@app.command()
def validate(
    tools_file: str | None = typer.Option(
        None, "--tools", help="JSON file with tool schemas (uses defaults if not provided)"
    ),
    show_grammar: bool = typer.Option(False, "--show-grammar", help="Print the generated grammar"),
) -> None:
    """Validate the EBNF grammar syntax."""
    tools = SAMPLE_TOOLS
    if tools_file:
        import json
        tools = json.loads(Path(tools_file).read_text())

    try:
        grammar = build_functiongemma_grammar(tools)
    except Exception as e:
        typer.echo(f"Grammar generation failed: {e}", err=True)
        raise typer.Exit(1)

    if show_grammar:
        typer.echo("Generated grammar:")
        typer.echo("-" * 60)
        typer.echo(grammar)
        typer.echo("-" * 60)
        typer.echo()

    result = validate_ebnf_syntax(grammar)

    if result.errors:
        typer.echo("ERRORS:", err=True)
        for error in result.errors:
            typer.echo(f"  - {error}", err=True)

    if result.warnings:
        typer.echo("WARNINGS:")
        for warning in result.warnings:
            typer.echo(f"  - {warning}")

    if result.valid:
        typer.echo("Grammar syntax is valid.")
        raise typer.Exit(0)
    else:
        typer.echo("Grammar syntax is INVALID.", err=True)
        raise typer.Exit(1)


@app.command()
def test(
    input_text: str | None = typer.Option(None, "--input", "-i", help="Test a specific input string"),
    run_samples: bool = typer.Option(True, "--samples/--no-samples", help="Run sample test cases"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """Test the grammar against sample inputs."""
    tools = SAMPLE_TOOLS

    try:
        grammar = build_functiongemma_grammar(tools)
    except Exception as e:
        typer.echo(f"Grammar generation failed: {e}", err=True)
        raise typer.Exit(1)

    if verbose:
        typer.echo("Grammar:")
        typer.echo(grammar)
        typer.echo()

    passed = 0
    failed = 0

    if input_text:
        matches, result = test_string_against_grammar(input_text, grammar, tools)
        if matches:
            typer.echo(f"MATCH: tool={result}")
            typer.echo(f"  Input: {input_text}")
        else:
            typer.echo(f"NO MATCH: {result}")
            typer.echo(f"  Input: {input_text}")
        return

    if run_samples:
        typer.echo("Testing VALID samples (should all match):")
        typer.echo("-" * 60)
        for sample in VALID_SAMPLES:
            matches, result = test_string_against_grammar(sample, grammar, tools)
            status = "PASS" if matches else "FAIL"
            if matches:
                passed += 1
                typer.echo(f"  [{status}] tool={result}")
            else:
                failed += 1
                typer.echo(f"  [{status}] {result}")
            if verbose:
                typer.echo(f"        Input: {sample[:60]}...")

        typer.echo()
        typer.echo("Testing INVALID samples (should NOT match):")
        typer.echo("-" * 60)
        for sample in INVALID_SAMPLES:
            matches, result = test_string_against_grammar(sample, grammar, tools)
            # For invalid samples, NOT matching is correct
            status = "PASS" if not matches else "FAIL"
            if not matches:
                passed += 1
                typer.echo(f"  [{status}] Correctly rejected")
            else:
                failed += 1
                typer.echo(f"  [{status}] Should have rejected but matched: {result}")
            if verbose:
                typer.echo(f"        Input: {sample[:60]}...")

        typer.echo()
        typer.echo(f"Results: {passed} passed, {failed} failed")

        if failed > 0:
            raise typer.Exit(1)


@app.command()
def generate(
    tool_names: list[str] = typer.Argument(..., help="Tool names to include in grammar"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file (stdout if not specified)"),
) -> None:
    """Generate a grammar for specific tool names."""
    tools = [
        {
            "type": "function",
            "function": {"name": name, "description": f"Tool {name}"},
        }
        for name in tool_names
    ]

    try:
        grammar = build_functiongemma_grammar(tools)
    except Exception as e:
        typer.echo(f"Grammar generation failed: {e}", err=True)
        raise typer.Exit(1)

    if output:
        Path(output).write_text(grammar)
        typer.echo(f"Grammar written to {output}")
    else:
        typer.echo(grammar)


@app.command()
def check_xgrammar() -> None:
    """Check if xgrammar package is available for full validation."""
    try:
        import xgrammar
        typer.echo(f"xgrammar is available: {xgrammar.__version__}")
        typer.echo("Full grammar validation is supported.")
    except ImportError:
        typer.echo("xgrammar is NOT installed.")
        typer.echo("Install with: pip install xgrammar")
        typer.echo("Without xgrammar, only basic syntax validation is available.")
        raise typer.Exit(1)


@app.command()
def full_test() -> None:
    """Run comprehensive grammar tests."""
    tools = SAMPLE_TOOLS

    typer.echo("=" * 60)
    typer.echo("GRAMMAR TEST HARNESS - Full Test Suite")
    typer.echo("=" * 60)
    typer.echo()

    # Step 1: Generate grammar
    typer.echo("Step 1: Generate grammar")
    typer.echo("-" * 40)
    try:
        grammar = build_functiongemma_grammar(tools)
        typer.echo("Grammar generated successfully.")
    except Exception as e:
        typer.echo(f"FAILED: {e}", err=True)
        raise typer.Exit(1)

    typer.echo()
    typer.echo("Generated grammar:")
    for line in grammar.split("\n"):
        typer.echo(f"  {line}")
    typer.echo()

    # Step 2: Validate EBNF syntax
    typer.echo("Step 2: Validate EBNF syntax")
    typer.echo("-" * 40)
    result = validate_ebnf_syntax(grammar)

    if result.errors:
        typer.echo("ERRORS found:")
        for error in result.errors:
            typer.echo(f"  - {error}")
    else:
        typer.echo("No syntax errors found.")

    if result.warnings:
        typer.echo("Warnings:")
        for warning in result.warnings:
            typer.echo(f"  - {warning}")

    typer.echo()

    # Step 3: Test against samples
    typer.echo("Step 3: Test against sample inputs")
    typer.echo("-" * 40)

    all_passed = True

    typer.echo("Valid samples (should match):")
    for i, sample in enumerate(VALID_SAMPLES, 1):
        matches, tool = test_string_against_grammar(sample, grammar, tools)
        status = "PASS" if matches else "FAIL"
        if not matches:
            all_passed = False
        typer.echo(f"  {i}. [{status}] {sample[:50]}...")

    typer.echo()
    typer.echo("Invalid samples (should NOT match):")
    for i, sample in enumerate(INVALID_SAMPLES, 1):
        matches, _ = test_string_against_grammar(sample, grammar, tools)
        status = "PASS" if not matches else "FAIL"
        if matches:
            all_passed = False
        typer.echo(f"  {i}. [{status}] {sample[:50]}...")

    typer.echo()
    typer.echo("=" * 60)
    if all_passed and result.valid:
        typer.echo("ALL TESTS PASSED")
        raise typer.Exit(0)
    else:
        typer.echo("SOME TESTS FAILED")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
