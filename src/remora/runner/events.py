"""Shared proposal and event models used by runner/LSP integrations."""

from __future__ import annotations

import difflib
import random
import string

from lsprotocol import types as lsp
from pydantic import BaseModel, Field, computed_field, model_validator


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


class LspAgentEvent(BaseModel):
    event_id: str = Field(default_factory=generate_id)
    event_type: str
    timestamp: float
    correlation_id: str
    agent_id: str | None = None
    summary: str = ""
    payload: dict = Field(default_factory=dict)


class LspHumanChatEvent(LspAgentEvent):
    to_agent: str = ""
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "HumanChatEvent")
        values.setdefault("summary", f"Human message to {values.get('to_agent', '')}")
        return values


class LspAgentMessageEvent(LspAgentEvent):
    from_agent: str = ""
    to_agent: str = ""
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "AgentMessageEvent")
        values.setdefault("summary", f"Message from {values.get('from_agent', '')} to {values.get('to_agent', '')}")
        return values


class LspRewriteProposalEvent(LspAgentEvent):
    proposal_id: str = ""
    diff: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "RewriteProposalEvent")
        values.setdefault("summary", f"Rewrite proposal from {values.get('agent_id', '')}")
        return values


class LspRewriteAppliedEvent(LspAgentEvent):
    agent_id: str = ""
    proposal_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "RewriteAppliedEvent")
        values.setdefault("summary", f"Proposal {values.get('proposal_id', '')} accepted")
        return values


class LspRewriteRejectedEvent(LspAgentEvent):
    agent_id: str = ""
    proposal_id: str = ""
    feedback: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "RewriteRejectedEvent")
        values.setdefault("summary", "Proposal rejected with feedback")
        return values


class LspAgentErrorEvent(LspAgentEvent):
    error: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "AgentErrorEvent")
        values.setdefault("summary", f"Error: {values.get('error', '')[:50]}")
        return values


RewriteProposal.model_rebuild()
LspAgentEvent.model_rebuild()
LspHumanChatEvent.model_rebuild()
LspAgentMessageEvent.model_rebuild()
LspRewriteProposalEvent.model_rebuild()
LspRewriteAppliedEvent.model_rebuild()
LspRewriteRejectedEvent.model_rebuild()
LspAgentErrorEvent.model_rebuild()

