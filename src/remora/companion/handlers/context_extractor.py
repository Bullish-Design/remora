from __future__ import annotations

import os
from pathlib import Path
from remora.core.events.agent_events import _FrozenEvent
from remora.core.events.interaction_events import CursorFocusEvent
from remora.companion.events import CompanionContextExtracted
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState

def _detect_content_type(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    code_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
        ".rs", ".go", ".rb", ".php", ".swift", ".kt", ".scala", ".lua",
        ".sh", ".bash", ".zsh", ".vim", ".el",
    }
    markdown_extensions = {".md", ".markdown", ".mdx", ".rst"}
    if suffix in code_extensions:
        return "code"
    elif suffix in markdown_extensions:
        return "markdown"
    return "prose"

def _extract_structure_python(lines: list[str], cursor_line: int) -> dict[str, str | None] | None:
    import re
    def_pattern = re.compile(r"^(\s*)(class|def|async def)\s+(\w+)")
    current_indent = (
        len(lines[cursor_line - 1]) - len(lines[cursor_line - 1].lstrip()) 
        if cursor_line <= len(lines) else 0
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
        return {
            "type": containing_type,
            "name": containing_name,
            "parent": parent_name
        }
    return None

def _extract_structure_markdown(lines: list[str], cursor_line: int) -> dict[str, str | None] | None:
    import re
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
    for i in range(min(cursor_line - 1, len(lines) - 1), -1, -1):
        match = heading_pattern.match(lines[i])
        if match:
            hashes, heading_text = match.groups()
            return {
                "type": "heading",
                "name": heading_text.strip(),
                "parent": None
            }
    return None


class ContextExtractorHandler(CompanionHandlerBase):
    """Extracts context around cursor position."""
    
    def __init__(self, agent_id: str, context_lines_before: int = 50, context_lines_after: int = 50, max_file_size_bytes: int = 1_000_000) -> None:
        super().__init__(agent_id)
        self.context_lines_before = context_lines_before
        self.context_lines_after = context_lines_after
        self.max_file_size_bytes = max_file_size_bytes

    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, CursorFocusEvent):
            return []
            
        file_path = Path(event.file_path)
        if not file_path.exists() or file_path.stat().st_size > self.max_file_size_bytes:
            return []
            
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
            
        lines = content.split("\n")
        total_lines = len(lines)
        line = event.line
        
        start_line = max(0, line - 1 - self.context_lines_before)
        end_line = min(total_lines, line + self.context_lines_after)
        region_lines = lines[start_line:end_line]
        region_text = "\n".join(region_lines)
        
        content_type = _detect_content_type(event.file_path)
        
        struct_info = None
        if content_type == "code" and event.file_path.endswith(".py"):
            struct_info = _extract_structure_python(lines, line)
        elif content_type == "markdown":
            struct_info = _extract_structure_markdown(lines, line)
            
        structure_type = struct_info["type"] if struct_info else "file"
        structure_name = struct_info["name"] if struct_info else file_path.name
        parent = struct_info["parent"] if struct_info and struct_info.get("parent") else None
        
        scope_path = (parent, structure_name) if parent else (structure_name,)
        if not scope_path[0]:
            scope_path = (file_path.name,)
            
        # Optional: cache AST parse results in workspace here if needed
            
        return [CompanionContextExtracted(
            file=event.file_path,
            line=line,
            structure_type=structure_type or "",
            structure_name=structure_name or "",
            content_type=content_type,
            surrounding_code=region_text,
            scope_path=tuple(str(s) for s in scope_path if s)
        )]
