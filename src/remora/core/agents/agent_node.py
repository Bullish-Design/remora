"""AgentNode unified model.

Single Pydantic model that serves as DB row, LLM prompt source,
and LSP protocol response. No subclasses. Specialization is data.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from lsprotocol import types as lsp
from pydantic import BaseModel, ConfigDict, Field

from remora.core.events.subscriptions import SubscriptionPattern

# Maps file extensions to (display name, code fence language)
_LANG_BY_EXT: dict[str, tuple[str, str]] = {
    ".py": ("Python", "python"),
    ".js": ("JavaScript", "javascript"),
    ".ts": ("TypeScript", "typescript"),
    ".go": ("Go", "go"),
    ".rs": ("Rust", "rust"),
    ".md": ("Markdown", "markdown"),
    ".toml": ("TOML", "toml"),
    ".yaml": ("YAML", "yaml"),
    ".yml": ("YAML", "yaml"),
    ".json": ("JSON", "json"),
}


class ToolSchema(BaseModel):
    """Schema for an agent tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_llm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_code_action(self, node_id: str) -> Any:
        return lsp.CodeAction(
            title=self.description,
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title=self.name,
                command=f"remora.tool.{self.name}",
                arguments=[node_id],
            ),
        )


class AgentNode(BaseModel):
    """Unified agent model: DB row, LLM prompt, and LSP response in one object.

    No subclasses. Specialization via data fields populated by extension configs.
    """

    model_config = ConfigDict(frozen=False)

    # --- Identity (from CSTNode via event projection) ---
    node_id: str
    node_type: str  # "function", "class", "method", "file", "section", "table"
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    start_byte: int = 0
    end_byte: int = 0
    source_code: str
    source_hash: str

    # --- Graph context (from edges table) ---
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # --- Runtime state (from event projections) ---
    status: str = "idle"  # "idle", "running", "error", "pending_approval"
    last_trigger_event: str = ""
    last_completed_at: float | None = None

    # --- Specialization (from extension config matching) ---
    extension_name: str | None = None
    custom_system_prompt: str = ""
    mounted_workspaces: list[str] = Field(default_factory=list)
    extra_tools: list[ToolSchema] = Field(default_factory=list)
    extra_subscriptions: list[SubscriptionPattern] = Field(default_factory=list)

    # --- Serialization ---

    def to_row(self) -> dict[str, Any]:
        """Serialize to a dict suitable for SQLite INSERT."""
        data = self.model_dump()
        data["caller_ids"] = json.dumps(data["caller_ids"])
        data["callee_ids"] = json.dumps(data["callee_ids"])
        data["extra_tools"] = json.dumps([t.model_dump() for t in self.extra_tools])
        data["extra_subscriptions"] = json.dumps([s.model_dump() for s in self.extra_subscriptions])
        data["mounted_workspaces"] = json.dumps(data["mounted_workspaces"])
        return data

    @classmethod
    def from_row(cls, row: sqlite3.Row | dict) -> AgentNode:
        """Hydrate from a SQLite row."""
        data = dict(row)
        data["caller_ids"] = json.loads(data.get("caller_ids") or "[]")
        data["callee_ids"] = json.loads(data.get("callee_ids") or "[]")
        data["extra_tools"] = [ToolSchema(**t) for t in json.loads(data.get("extra_tools") or "[]")]
        data["extra_subscriptions"] = [
            SubscriptionPattern(**s) for s in json.loads(data.get("extra_subscriptions") or "[]")
        ]
        data["mounted_workspaces"] = json.loads(data.get("mounted_workspaces") or "[]")
        return cls(**data)

    # --- LSP helper ---

    def to_range(self) -> Any:
        return lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=0),
            end=lsp.Position(line=self.end_line - 1, character=0),
        )

    # --- LLM prompt ---

    def to_system_prompt(self) -> str:
        """Generate the LLM system prompt from all fields."""
        ext = PurePosixPath(self.file_path).suffix.lower()
        lang_display, lang_fence = _LANG_BY_EXT.get(ext, ("", ""))
        lang_prefix = f"{lang_display} " if lang_display else ""
        prompt = f"""You are an autonomous AI agent embodying a {lang_prefix}{self.node_type}: `{self.name}`

# Identity
- Node ID: {self.node_id}
- Location: {self.file_path}:{self.start_line}-{self.end_line}
- Parent: {self.parent_id or "None (top-level)"}

# Your Source Code
```{lang_fence}
{self.source_code}
```

# Graph Context
- Called by: {", ".join(self.caller_ids) or "None"}
- You call: {", ".join(self.callee_ids) or "None"}

# Core Rules
1. You may ONLY edit your own body using `rewrite_self()`.
2. To request changes elsewhere, use `message_node(target_id, request)`.
3. All edits are proposals -- the human must approve before they apply.
"""
        if self.custom_system_prompt:
            prompt += f"\n# Specialization ({self.extension_name})\n{self.custom_system_prompt}\n"
        if self.mounted_workspaces:
            prompt += "\n# Available Workspaces\n" + "\n".join(f"- {w}" for w in self.mounted_workspaces) + "\n"
        return prompt

    # --- LSP conversions ---

    def to_code_lens(self) -> Any:
        status_icon = {
            "idle": "\u25cf",
            "running": "\u25b6",
            "pending_approval": "\u23f8",
            "error": "\u25cb",
        }
        return lsp.CodeLens(
            range=lsp.Range(
                start=lsp.Position(line=self.start_line - 1, character=0),
                end=lsp.Position(line=self.start_line - 1, character=0),
            ),
            command=lsp.Command(
                title=f"{status_icon.get(self.status, '?')} {self.node_id}",
                command="remora.selectAgent",
                arguments=[self.node_id],
            ),
        )

    def to_hover(self, recent_events: list | None = None) -> Any:
        lines = [
            f"## {self.name}",
            f"**ID:** `{self.node_id}`  **Type:** {self.node_type}  **Status:** {self.status}",
            f"**Parent:** `{self.parent_id or 'None'}`",
            f"**Callers:** {', '.join(f'`{c}`' for c in self.caller_ids) or 'None'}",
            f"**Callees:** {', '.join(f'`{c}`' for c in self.callee_ids) or 'None'}",
        ]
        if self.extension_name:
            lines.append(f"**Extension:** {self.extension_name}")
        if recent_events:
            lines.extend(["", "---", "", "### Recent Events"])
            for ev in recent_events:
                if isinstance(ev, dict):
                    event_type = ev.get("event_type", "")
                    summary = ev.get("payload", {}).get("summary", "")
                else:
                    event_type = ev.event_type
                    summary = ev.summary
                lines.append(f"- `{event_type}` {summary}")
        return lsp.Hover(
            contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value="\n".join(lines)),
            range=self.to_range(),
        )

    def to_code_actions(self) -> Any:
        actions = [
            lsp.CodeAction(
                title="Chat with this agent",
                kind=lsp.CodeActionKind.Empty,
                command=lsp.Command(
                    title="Chat",
                    command="remora.chat",
                    arguments=[self.node_id],
                ),
            ),
            lsp.CodeAction(
                title="Ask agent to rewrite itself",
                kind=lsp.CodeActionKind.RefactorRewrite,
                command=lsp.Command(
                    title="Rewrite",
                    command="remora.requestRewrite",
                    arguments=[self.node_id],
                ),
            ),
            lsp.CodeAction(
                title="Message another agent",
                kind=lsp.CodeActionKind.Empty,
                command=lsp.Command(
                    title="Message",
                    command="remora.messageNode",
                    arguments=[self.node_id],
                ),
            ),
        ]
        for tool in self.extra_tools:
            actions.append(tool.to_code_action(self.node_id))
        return actions

    def to_document_symbol(self) -> Any:
        kind_map = {
            "function": lsp.SymbolKind.Function,
            "method": lsp.SymbolKind.Method,
            "class": lsp.SymbolKind.Class,
            "file": lsp.SymbolKind.File,
            "section": lsp.SymbolKind.String,
            "table": lsp.SymbolKind.Object,
            "note": lsp.SymbolKind.File,
            "todo": lsp.SymbolKind.Event,
        }
        return lsp.DocumentSymbol(
            name=f"{self.name} [{self.status}]",
            kind=kind_map.get(self.node_type, lsp.SymbolKind.Variable),
            range=self.to_range(),
            selection_range=self.to_range(),
            detail=self.extension_name or self.node_type,
        )
