"""Runner-owned proposal and ID models.

RewriteProposal describes a pending code change that the runner creates
and the server (LSP or headless) stores and dispatches.
"""

from __future__ import annotations

import difflib
import random
import string

from lsprotocol import types as lsp
from pydantic import BaseModel, computed_field


def generate_id() -> str:
    body = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"rm_{body}"


class RewriteProposal(BaseModel):
    proposal_id: str
    agent_id: str
    file_path: str
    old_source: str
    new_source: str
    start_line: int
    end_line: int
    reasoning: str = ""
    correlation_id: str = ""

    @computed_field
    @property
    def diff(self) -> str:
        return "\n".join(
            difflib.unified_diff(
                self.old_source.splitlines(),
                self.new_source.splitlines(),
                lineterm="",
            )
        )

    def to_workspace_edit(self) -> lsp.WorkspaceEdit:
        return lsp.WorkspaceEdit(
            changes={
                self.file_path: [
                    lsp.TextEdit(
                        range=lsp.Range(
                            start=lsp.Position(line=self.start_line - 1, character=0),
                            end=lsp.Position(line=self.end_line, character=0),
                        ),
                        new_text=self.new_source + "\n",
                    )
                ]
            }
        )

    def to_diagnostic(self) -> lsp.Diagnostic:
        return lsp.Diagnostic(
            range=lsp.Range(
                start=lsp.Position(line=self.start_line - 1, character=0),
                end=lsp.Position(line=self.end_line - 1, character=0),
            ),
            severity=lsp.DiagnosticSeverity.Information,
            source="remora",
            code=self.proposal_id,
            message=f"Agent proposes rewrite: {self.reasoning[:100]}",
            data={"proposal_id": self.proposal_id, "diff": self.diff},
        )

    def to_code_actions(self) -> list[lsp.CodeAction]:
        return [
            lsp.CodeAction(
                title="Accept rewrite",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[self.to_diagnostic()],
                edit=self.to_workspace_edit(),
                command=lsp.Command(
                    title="Accept",
                    command="remora.acceptProposal",
                    arguments=[self.proposal_id],
                ),
            ),
            lsp.CodeAction(
                title="Reject with feedback",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[self.to_diagnostic()],
                command=lsp.Command(
                    title="Reject",
                    command="remora.rejectProposal",
                    arguments=[self.proposal_id],
                ),
            ),
        ]


__all__ = ["RewriteProposal", "generate_id"]
