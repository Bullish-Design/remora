from __future__ import annotations

import difflib
import random
import string

from lsprotocol import types as lsp
from pydantic import BaseModel, Field, computed_field, model_validator

from remora.core.events import (
    AgentCompleteEvent as CoreAgentCompleteEvent,
    AgentErrorEvent as CoreAgentErrorEvent,
    AgentMessageEvent as CoreAgentMessageEvent,
    ManualTriggerEvent as CoreManualTriggerEvent,
)


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
                title="\u2705 Accept rewrite",
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
                title="\u274c Reject with feedback",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[self.to_diagnostic()],
                command=lsp.Command(
                    title="Reject",
                    command="remora.rejectProposal",
                    arguments=[self.proposal_id],
                ),
            ),
        ]


class AgentEvent(BaseModel):
    event_id: str = Field(default_factory=generate_id)
    event_type: str
    timestamp: float
    correlation_id: str
    agent_id: str | None = None
    summary: str = ""
    payload: dict = Field(default_factory=dict)

    def to_core_event(self):
        raise NotImplementedError

    @classmethod
    def from_core_event(cls, event) -> AgentEvent:
        event_type = type(event).__name__
        return cls(
            event_type=event_type,
            timestamp=getattr(event, "timestamp", 0.0),
            correlation_id=getattr(event, "correlation_id", "") or "",
            agent_id=getattr(event, "agent_id", None),
            summary=str(event),
        )


class HumanChatEvent(AgentEvent):
    to_agent: str = ""
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "HumanChatEvent")
        values.setdefault("summary", f"Human message to {values.get('to_agent', '')}")
        return values

    def to_core_event(self):
        return CoreAgentMessageEvent(
            from_agent="human",
            to_agent=self.to_agent,
            content=self.message,
            correlation_id=self.correlation_id or None,
            timestamp=self.timestamp,
        )


class AgentMessageEvent(AgentEvent):
    from_agent: str = ""
    to_agent: str = ""
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "AgentMessageEvent")
        values.setdefault("summary", f"Message from {values.get('from_agent', '')} to {values.get('to_agent', '')}")
        return values

    def to_core_event(self):
        return CoreAgentMessageEvent(
            from_agent=self.from_agent,
            to_agent=self.to_agent,
            content=self.message,
            correlation_id=self.correlation_id or None,
            timestamp=self.timestamp,
        )


class RewriteProposalEvent(AgentEvent):
    proposal_id: str = ""
    diff: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "RewriteProposalEvent")
        values.setdefault("summary", f"Rewrite proposal from {values.get('agent_id', '')}")
        return values

    def to_core_event(self):
        return CoreManualTriggerEvent(
            to_agent=self.agent_id or "",
            reason=self.summary,
            timestamp=self.timestamp,
        )


class RewriteAppliedEvent(AgentEvent):
    agent_id: str = ""
    proposal_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "RewriteAppliedEvent")
        values.setdefault("summary", f"Proposal {values.get('proposal_id', '')} accepted")
        return values

    def to_core_event(self):
        return CoreAgentCompleteEvent(
            graph_id=self.correlation_id or "lsp",
            agent_id=self.agent_id or "",
            result_summary=self.summary,
            response=self.proposal_id,
            timestamp=self.timestamp,
        )


class RewriteRejectedEvent(AgentEvent):
    agent_id: str = ""
    proposal_id: str = ""
    feedback: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "RewriteRejectedEvent")
        values.setdefault("summary", "Proposal rejected with feedback")
        return values

    def to_core_event(self):
        return CoreAgentErrorEvent(
            graph_id=self.correlation_id or "lsp",
            agent_id=self.agent_id or "",
            error=self.feedback or self.summary,
            timestamp=self.timestamp,
        )


class AgentErrorEvent(AgentEvent):
    error: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "AgentErrorEvent")
        values.setdefault("summary", f"Error: {values.get('error', '')[:50]}")
        return values

    def to_core_event(self):
        return CoreAgentErrorEvent(
            graph_id=self.correlation_id or "lsp",
            agent_id=self.agent_id or "",
            error=self.error,
            timestamp=self.timestamp,
        )


# Resolve forward references explicitly for Pydantic
RewriteProposal.model_rebuild()
AgentEvent.model_rebuild()
HumanChatEvent.model_rebuild()
AgentMessageEvent.model_rebuild()
RewriteProposalEvent.model_rebuild()
RewriteAppliedEvent.model_rebuild()
RewriteRejectedEvent.model_rebuild()
AgentErrorEvent.model_rebuild()
