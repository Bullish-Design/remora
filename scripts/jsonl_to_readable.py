#!/usr/bin/env python3
"""
Convert JSONL conversation files to human-readable Markdown format.

Uses Pydantic models for validation and string representation.
Malformed lines are skipped with a FAILURE note in the output.

Usage: python jsonl_to_readable.py <path_to_jsonl_file>
Output: Creates <jsonl_name>_readable.md in the same directory as the input file.
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class FunctionCall(BaseModel):
    """Represents a function call within a tool call."""

    name: Optional[str] = None
    arguments: dict = Field(default_factory=dict)

    def __str__(self) -> str:
        args_str = json.dumps(self.arguments) if self.arguments else "None"
        return f"`{self.name or 'None'}` (Arguments: `{args_str}`)"


class ToolCall(BaseModel):
    """Represents a tool call in an assistant message."""

    type: Optional[str] = None
    function: FunctionCall = Field(default_factory=FunctionCall)

    def __str__(self) -> str:
        lines = [f"  - Tool Call: `{self.function.name or 'None'}`"]
        lines.append(f"    - Type: `{self.type or 'None'}`")
        args_str = json.dumps(self.function.arguments) if self.function.arguments else "None"
        lines.append(f"    - Arguments: `{args_str}`")
        return "\n".join(lines)


class Message(BaseModel):
    """Represents a message in the conversation history."""

    role: Optional[str] = None
    content: Optional[str] = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @field_validator("tool_calls", mode="before")
    @classmethod
    def validate_tool_calls(cls, v: Any) -> list[ToolCall]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    def __str__(self) -> str:
        role_display = self.role.capitalize() if self.role else "Unknown"
        lines = [f"**{role_display}**"]

        if self.content:
            lines[-1] += f': "{self.content}"'
        else:
            lines[-1] += ": None"

        if self.tool_calls:
            lines.append("")
            for call in self.tool_calls:
                lines.append(str(call))

        return "\n".join(lines)


class Answer(BaseModel):
    """Represents the final answer/function call."""

    name: Optional[str] = None
    parameters: dict = Field(default_factory=dict)

    def __str__(self) -> str:
        name_display = f"`{self.name}`" if self.name else "None"
        params_str = json.dumps(self.parameters) if self.parameters else "None"
        return f"**Function**: {name_display}\n**Parameters**: `{params_str}`"


class ConversationEntry(BaseModel):
    """Represents a single entry in the JSONL file."""

    question: list[Message] = Field(default_factory=list)
    answer: Optional[Answer] = None

    @field_validator("question", mode="before")
    @classmethod
    def parse_question(cls, v: Any) -> list[Message]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
        elif isinstance(v, list):
            return v
        return []

    @field_validator("answer", mode="before")
    @classmethod
    def parse_answer(cls, v: Any) -> Optional[Answer]:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return Answer.model_validate(parsed)
            except json.JSONDecodeError:
                pass
        elif isinstance(v, dict):
            return Answer.model_validate(v)
        return None

    def __str__(self) -> str:
        lines = []

        # Conversation History
        lines.append("### Conversation History")
        if self.question:
            for msg in self.question:
                lines.append(str(msg))
                lines.append("")
        else:
            lines.append("*(No conversation history)*")
            lines.append("")

        # Answer
        lines.append("### Answer")
        if self.answer:
            lines.append(str(self.answer))
        else:
            lines.append("*(No answer provided)*")

        return "\n".join(lines)


def process_jsonl(input_path: Path) -> tuple[str, int, int]:
    """Process the JSONL file and return formatted Markdown content.

    Args:
        input_path: Path to the JSONL file

    Returns:
        Tuple of (markdown_content, valid_count, failure_count)
    """
    if not input_path.exists():
        print(f"Error: File '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)

    if not input_path.is_file():
        print(f"Error: '{input_path}' is not a file.", file=sys.stderr)
        sys.exit(1)

    output_lines: list[str] = []
    valid_count = 0
    failure_count = 0

    with open(input_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            try:
                # Parse the entry using Pydantic
                entry = ConversationEntry.model_validate_json(line)

                # Format conversation entry
                output_lines.append(f"## Conversation {valid_count + 1}")
                output_lines.append("")
                output_lines.append(str(entry))
                output_lines.append("")
                output_lines.append("---")
                output_lines.append("")

                valid_count += 1

            except Exception as e:
                failure_count += 1
                output_lines.append(f"**FAILURE:** Line {line_num}, {line}")
                output_lines.append(f"*(Error: {e!s})*")
                output_lines.append("")
                output_lines.append("---")
                output_lines.append("")

    # Build final markdown
    header = f"""# JSONL to Readable Markdown

Source: `{input_path.name}`

- Valid entries: {valid_count}
- Failed lines: {failure_count}
- Total lines processed: {valid_count + failure_count}

---

"""

    markdown = header + "\n".join(output_lines)

    return markdown, valid_count, failure_count


def main() -> None:
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python jsonl_to_readable.py <path_to_jsonl_file>", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])

    # Generate output path
    output_path = input_path.parent / f"{input_path.stem}_readable.md"

    print(f"Processing: {input_path}")

    # Process the file
    markdown_content, valid_count, failure_count = process_jsonl(input_path)

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)

    print(f"Output saved to: {output_path}")
    print(f"Summary: {valid_count} valid entries, {failure_count} failures")


if __name__ == "__main__":
    main()
