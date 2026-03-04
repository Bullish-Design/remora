"""Context extractor agent.

Extracts text region around cursor position and detects content type.
Writes to /companion/context/* workspace paths.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora_demo.companion.agents.base import AgentBase, WorkspaceInterface, subscribe
from remora_demo.companion.models.events import CursorMoved
from remora_demo.companion.models.workspace import CursorPosition, Structure


@dataclass
class ContextExtractorConfig:
    """Configuration for context extractor."""

    context_lines_before: int = 50
    context_lines_after: int = 50
    max_file_size_bytes: int = 1_000_000  # Skip files larger than 1MB


def _detect_content_type(file_path: str) -> str:
    """Detect content type from file extension."""
    suffix = Path(file_path).suffix.lower()

    code_extensions = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".rs",
        ".go",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".lua",
        ".sh",
        ".bash",
        ".zsh",
        ".vim",
        ".el",
    }
    markdown_extensions = {".md", ".markdown", ".mdx", ".rst"}

    if suffix in code_extensions:
        return "code"
    elif suffix in markdown_extensions:
        return "markdown"
    else:
        return "prose"


def _extract_structure_python(lines: list[str], cursor_line: int) -> Structure | None:
    """Extract Python structure context (function/class containing cursor)."""
    import re

    def_pattern = re.compile(r"^(\s*)(class|def|async def)\s+(\w+)")

    # Find containing scope by walking backwards
    current_indent = (
        len(lines[cursor_line - 1]) - len(lines[cursor_line - 1].lstrip()) if cursor_line <= len(lines) else 0
    )

    containing_name = None
    containing_type = None
    parent_name = None

    for i in range(min(cursor_line - 1, len(lines) - 1), -1, -1):
        line = lines[i]
        match = def_pattern.match(line)
        if match:
            indent_str, keyword, name = match.groups()
            indent = len(indent_str)

            if indent < current_indent or containing_name is None:
                if containing_name is None:
                    containing_name = name
                    containing_type = "class" if keyword == "class" else "function"
                    current_indent = indent
                elif indent < current_indent:
                    parent_name = name
                    break

    if containing_name:
        return Structure(
            structure_type=containing_type,
            name=containing_name,
            parent=parent_name,
            depth=0,
        )
    return None


def _extract_structure_markdown(lines: list[str], cursor_line: int) -> Structure | None:
    """Extract markdown structure context (heading containing cursor)."""
    import re

    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    # Walk backwards to find nearest heading
    for i in range(min(cursor_line - 1, len(lines) - 1), -1, -1):
        match = heading_pattern.match(lines[i])
        if match:
            hashes, heading_text = match.groups()
            return Structure(
                structure_type="heading",
                name=heading_text.strip(),
                parent=None,  # Could walk further back for parent heading
                depth=len(hashes),
            )
    return None


class ContextExtractor(AgentBase):
    """Extracts context around cursor position.

    Subscribes to: CursorMoved events
    Writes to:
        /companion/context/file_path
        /companion/context/cursor_position
        /companion/context/current_region
        /companion/context/content_type
        /companion/context/structure
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: ContextExtractorConfig | None = None,
    ) -> None:
        super().__init__("context_extractor")
        self.workspace = workspace
        self.config = config or ContextExtractorConfig()

    @subscribe(CursorMoved)
    async def on_cursor_moved(self, event: CursorMoved) -> None:
        """Handle cursor movement events."""
        await self.extract_context(event.file, event.line, event.col)

    async def extract_context(self, file: str, line: int, col: int) -> None:
        """Extract and write context for the given position."""
        file_path = Path(file)

        # Check file exists and is readable
        if not file_path.exists():
            return

        # Check file size
        if file_path.stat().st_size > self.config.max_file_size_bytes:
            return

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        lines = content.split("\n")
        total_lines = len(lines)

        # Calculate context window
        start_line = max(0, line - 1 - self.config.context_lines_before)
        end_line = min(total_lines, line + self.config.context_lines_after)

        # Extract region
        region_lines = lines[start_line:end_line]
        region_text = "\n".join(region_lines)

        # Detect content type
        content_type = _detect_content_type(file)

        # Extract structure
        structure = None
        if content_type == "code" and file.endswith(".py"):
            structure = _extract_structure_python(lines, line)
        elif content_type == "markdown":
            structure = _extract_structure_markdown(lines, line)

        # Write to workspace
        await self.workspace.write("/companion/context/file_path", file)
        self.record_output("/companion/context/file_path")

        await self.workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=line, col=col),
        )
        self.record_output("/companion/context/cursor_position")

        await self.workspace.write("/companion/context/current_region", region_text)
        self.record_output("/companion/context/current_region")

        await self.workspace.write("/companion/context/content_type", content_type)
        self.record_output("/companion/context/content_type")

        if structure:
            await self.workspace.write("/companion/context/structure", structure)
            self.record_output("/companion/context/structure")

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, CursorMoved):
            await self.on_cursor_moved(data)
