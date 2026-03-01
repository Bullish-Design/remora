# src/remora/lsp/bridge.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from lsprotocol import types as lsp


@runtime_checkable
class LSPExportable(Protocol):
    """Any object with these fields can export to LSP types."""

    remora_id: str
    node_type: str
    name: str
    file_path: str
    start_line: int
    end_line: int
    status: str


class LSPBridgeMixin:
    """Adds LSP conversion methods to agent identity objects."""

    def to_range(self) -> lsp.Range:
        return lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=0),
            end=lsp.Position(line=self.end_line - 1, character=0),
        )

    def to_code_lens(self) -> lsp.CodeLens:
        icons = {
            "active": "●",
            "running": "▶",
            "pending_approval": "⏸",
            "orphaned": "○",
        }
        return lsp.CodeLens(
            range=lsp.Range(
                start=lsp.Position(line=self.start_line - 1, character=0),
                end=lsp.Position(line=self.start_line - 1, character=0),
            ),
            command=lsp.Command(
                title=f"{icons.get(self.status, '?')} {self.remora_id}",
                command="remora.selectAgent",
                arguments=[self.remora_id],
            ),
        )

    def to_hover(self, recent_events: list | None = None) -> lsp.Hover:
        lines = [
            f"## {self.name}",
            f"**ID:** `{self.remora_id}`",
            f"**Type:** {self.node_type}",
            f"**Status:** {self.status}",
        ]
        if recent_events:
            lines.extend(["", "---", "", "### Recent Events"])
            for ev in recent_events:
                summary = getattr(ev, "summary", str(ev))
                lines.append(f"- {summary}")

        return lsp.Hover(
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value="\n".join(lines),
            ),
            range=self.to_range(),
        )
