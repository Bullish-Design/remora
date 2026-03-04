"""Content chunking for Companion indexing.

Splits code and markdown files into semantic chunks suitable for embedding.
Uses tree-sitter for code parsing where available.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from remora_demo.companion.indexing.store import Chunk


@dataclass
class ChunkConfig:
    """Configuration for chunking behavior."""

    # Code chunking
    max_code_chunk_lines: int = 100
    min_code_chunk_lines: int = 5
    include_imports_in_context: bool = True

    # Markdown chunking
    max_markdown_chunk_chars: int = 2000
    min_markdown_chunk_chars: int = 100
    split_on_headings: bool = True

    # General
    overlap_lines: int = 3  # Lines of overlap between chunks


def _generate_chunk_id(file_path: str, start_line: int, content: str) -> str:
    """Generate a stable ID for a chunk."""
    key = f"{file_path}:{start_line}:{content[:100]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _detect_content_type(file_path: Path) -> str:
    """Detect content type from file extension."""
    suffix = file_path.suffix.lower()

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
        ".fish",
        ".vim",
        ".el",
    }

    markdown_extensions = {".md", ".markdown", ".mdx", ".rst", ".txt"}

    if suffix in code_extensions:
        return "code"
    elif suffix in markdown_extensions:
        return "markdown"
    else:
        return "prose"


def chunk_python_file(file_path: Path, content: str) -> Iterator[Chunk]:
    """Chunk a Python file by function/class definitions.

    Uses simple regex-based parsing. For production, use tree-sitter.
    """
    lines = content.split("\n")

    # Pattern for function and class definitions
    def_pattern = re.compile(r"^(class|def|async def)\s+(\w+)")

    current_chunk_start = 0
    current_chunk_name: str | None = None
    current_chunk_type = "module"
    current_parent: str | None = None

    # Track class context for methods
    class_stack: list[tuple[str, int]] = []  # (name, indent)

    def emit_chunk(end_line: int) -> Chunk | None:
        if end_line <= current_chunk_start:
            return None

        chunk_lines = lines[current_chunk_start:end_line]
        chunk_content = "\n".join(chunk_lines)

        if not chunk_content.strip():
            return None

        return Chunk(
            id=_generate_chunk_id(str(file_path), current_chunk_start, chunk_content),
            file_path=str(file_path),
            content=chunk_content,
            content_type="code",
            chunk_type=current_chunk_type,
            start_line=current_chunk_start + 1,  # 1-indexed
            end_line=end_line,
            name=current_chunk_name,
            parent=current_parent,
        )

    for i, line in enumerate(lines):
        # Track indentation for class context
        indent = len(line) - len(line.lstrip())

        # Pop class stack if we've dedented past a class
        while class_stack and indent <= class_stack[-1][1] and line.strip():
            class_stack.pop()

        match = def_pattern.match(line.lstrip())
        if match:
            # Emit previous chunk
            chunk = emit_chunk(i)
            if chunk:
                yield chunk

            keyword, name = match.groups()
            current_chunk_start = i
            current_chunk_name = name

            if keyword == "class":
                current_chunk_type = "class"
                current_parent = class_stack[-1][0] if class_stack else None
                class_stack.append((name, indent))
            else:
                current_chunk_type = "function"
                current_parent = class_stack[-1][0] if class_stack else None

    # Emit final chunk
    chunk = emit_chunk(len(lines))
    if chunk:
        yield chunk


def chunk_markdown_file(file_path: Path, content: str, config: ChunkConfig | None = None) -> Iterator[Chunk]:
    """Chunk a markdown file by headings.

    Each heading starts a new chunk, with content until the next heading
    of equal or higher level.
    """
    config = config or ChunkConfig()
    lines = content.split("\n")

    # Pattern for markdown headings
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    current_chunk_start = 0
    current_heading: str | None = None
    current_level = 0
    heading_stack: list[str] = []  # Parent headings for context

    def emit_chunk(end_line: int) -> Chunk | None:
        if end_line <= current_chunk_start:
            return None

        chunk_lines = lines[current_chunk_start:end_line]
        chunk_content = "\n".join(chunk_lines)

        if not chunk_content.strip():
            return None

        # Skip if too small
        if len(chunk_content) < config.min_markdown_chunk_chars:
            return None

        return Chunk(
            id=_generate_chunk_id(str(file_path), current_chunk_start, chunk_content),
            file_path=str(file_path),
            content=chunk_content,
            content_type="markdown",
            chunk_type="section",
            start_line=current_chunk_start + 1,
            end_line=end_line,
            name=current_heading,
            parent=" > ".join(heading_stack) if heading_stack else None,
        )

    for i, line in enumerate(lines):
        match = heading_pattern.match(line)
        if match:
            # Emit previous chunk
            chunk = emit_chunk(i)
            if chunk:
                yield chunk

            hashes, heading_text = match.groups()
            level = len(hashes)

            # Update heading stack
            while heading_stack and current_level >= level:
                heading_stack.pop()
                current_level -= 1

            if current_heading:
                heading_stack.append(current_heading)

            current_heading = heading_text.strip()
            current_level = level
            current_chunk_start = i

    # Emit final chunk
    chunk = emit_chunk(len(lines))
    if chunk:
        yield chunk


def chunk_generic_file(file_path: Path, content: str, config: ChunkConfig | None = None) -> Iterator[Chunk]:
    """Chunk a generic file by paragraphs/line groups.

    Fallback for files without specific parsing support.
    """
    config = config or ChunkConfig()
    lines = content.split("\n")

    # Split on blank lines (paragraphs)
    current_chunk_start = 0
    current_chunk_lines: list[str] = []

    def emit_chunk(end_line: int) -> Chunk | None:
        if not current_chunk_lines:
            return None

        chunk_content = "\n".join(current_chunk_lines)
        if len(chunk_content) < config.min_markdown_chunk_chars:
            return None

        return Chunk(
            id=_generate_chunk_id(str(file_path), current_chunk_start, chunk_content),
            file_path=str(file_path),
            content=chunk_content,
            content_type="prose",
            chunk_type="paragraph",
            start_line=current_chunk_start + 1,
            end_line=end_line,
            name=None,
            parent=None,
        )

    for i, line in enumerate(lines):
        if not line.strip():
            # Blank line - maybe emit chunk
            if current_chunk_lines:
                chunk_content = "\n".join(current_chunk_lines)
                if len(chunk_content) >= config.max_markdown_chunk_chars:
                    chunk = emit_chunk(i)
                    if chunk:
                        yield chunk
                    current_chunk_lines = []
                    current_chunk_start = i + 1
        else:
            if not current_chunk_lines:
                current_chunk_start = i
            current_chunk_lines.append(line)

    # Emit final chunk
    if current_chunk_lines:
        chunk = emit_chunk(len(lines))
        if chunk:
            yield chunk


def chunk_file(file_path: Path, content: str | None = None, config: ChunkConfig | None = None) -> Iterator[Chunk]:
    """Chunk a file into semantic pieces.

    Automatically detects file type and uses appropriate chunking strategy.

    Args:
        file_path: Path to the file
        content: File content (if None, reads from file_path)
        config: Chunking configuration

    Yields:
        Chunk objects
    """
    if content is None:
        content = file_path.read_text(encoding="utf-8", errors="replace")

    content_type = _detect_content_type(file_path)

    if content_type == "code":
        if file_path.suffix == ".py":
            yield from chunk_python_file(file_path, content)
        else:
            # For other code files, fall back to generic chunking
            # TODO: Add tree-sitter support for other languages
            yield from chunk_generic_file(file_path, content, config)
    elif content_type == "markdown":
        yield from chunk_markdown_file(file_path, content, config)
    else:
        yield from chunk_generic_file(file_path, content, config)


def chunk_text(
    content: str,
    source_id: str,
    content_type: str = "prose",
    config: ChunkConfig | None = None,
) -> Iterator[Chunk]:
    """Chunk raw text content (e.g., from web clipper).

    Args:
        content: Text content to chunk
        source_id: Identifier for the source (URL, etc.)
        content_type: Type of content ("markdown", "prose", etc.)
        config: Chunking configuration

    Yields:
        Chunk objects
    """
    config = config or ChunkConfig()

    # Treat as markdown if it looks like markdown
    if content_type == "markdown" or re.search(r"^#{1,6}\s+", content, re.MULTILINE):
        # Create a fake path for chunking
        fake_path = Path(f"{source_id}.md")
        yield from chunk_markdown_file(fake_path, content, config)
    else:
        fake_path = Path(f"{source_id}.txt")
        yield from chunk_generic_file(fake_path, content, config)
