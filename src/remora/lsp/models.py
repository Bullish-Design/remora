from __future__ import annotations

import difflib
import hashlib
import random
import string
from typing import Literal

from lsprotocol import types as lsp
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from remora.core.events import (
    AgentCompleteEvent as CoreAgentCompleteEvent,
    AgentErrorEvent as CoreAgentErrorEvent,
    AgentMessageEvent as CoreAgentMessageEvent,
    ManualTriggerEvent as CoreManualTriggerEvent,
)


def generate_id() -> str:
    body = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"rm_{body}"


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: dict

    def to_code_action(self, agent_id: str) -> lsp.CodeAction:
        return lsp.CodeAction(
            title=f"\U0001f527 {self.name}",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title=self.name,
                command="remora.executeTool",
                arguments=[agent_id, self.name, self.parameters],
            ),
        )

    def to_llm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ASTAgentNode(BaseModel):
    model_config = ConfigDict(frozen=False)

    remora_id: str
    node_type: Literal["function", "class", "method", "file"]
    name: str
    file_path: str
    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0
    source_code: str
    source_hash: str
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)
    status: Literal["active", "orphaned", "running", "pending_approval"] = "active"
    pending_proposal_id: str | None = None
    custom_system_prompt: str = ""
    mounted_workspaces: str = ""
    extra_tools: list[ToolSchema] = Field(default_factory=list)

    def to_document_symbol(self) -> lsp.DocumentSymbol:
        kind_map = {
            "function": lsp.SymbolKind.Function,
            "method": lsp.SymbolKind.Method,
            "class": lsp.SymbolKind.Class,
            "file": lsp.SymbolKind.File,
        }
        return lsp.DocumentSymbol(
            name=f"{self.name} [{self.remora_id}]",
            kind=kind_map[self.node_type],
            range=self.to_range(),
            selection_range=self.to_range(),
            detail=f"remora:{self.status}",
            children=[],
        )

    def to_range(self) -> lsp.Range:
        return lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=self.start_col),
            end=lsp.Position(line=self.end_line - 1, character=self.end_col),
        )

    def to_code_lens(self) -> lsp.CodeLens:
        status_icon = {
            "active": "\u25cf",
            "running": "\u25b6",
            "pending_approval": "\u23f8",
            "orphaned": "\u25cb",
        }
        return lsp.CodeLens(
            range=lsp.Range(
                start=lsp.Position(line=self.start_line - 1, character=0),
                end=lsp.Position(line=self.start_line - 1, character=0),
            ),
            command=lsp.Command(
                title=f"{status_icon[self.status]} {self.remora_id}",
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
            "",
            f"**Parent:** `{self.parent_id or 'None'}`",
            f"**Callers:** {', '.join(f'`{c}`' for c in self.caller_ids) or 'None'}",
            f"**Callees:** {', '.join(f'`{c}`' for c in self.callee_ids) or 'None'}",
        ]

        if self.custom_system_prompt:
            lines.extend(["", "---", "", f"*{self.custom_system_prompt[:200]}...*"])

        if recent_events:
            lines.extend(["", "---", "", "### Recent Events"])
            for ev in recent_events:
                lines.append(f"- `{ev.event_type}` {ev.summary}")

        return lsp.Hover(
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value="\n".join(lines),
            ),
            range=self.to_range(),
        )

    def to_code_actions(self) -> list[lsp.CodeAction]:
        actions = []

        actions.append(
            lsp.CodeAction(
                title="\U0001f4ac Chat with this agent",
                kind=lsp.CodeActionKind.Empty,
                command=lsp.Command(
                    title="Chat",
                    command="remora.chat",
                    arguments=[self.remora_id],
                ),
            )
        )

        actions.append(
            lsp.CodeAction(
                title="\u270f Ask agent to rewrite itself",
                kind=lsp.CodeActionKind.RefactorRewrite,
                command=lsp.Command(
                    title="Rewrite",
                    command="remora.requestRewrite",
                    arguments=[self.remora_id],
                ),
            )
        )

        actions.append(
            lsp.CodeAction(
                title="\U0001f4e4 Message another agent",
                kind=lsp.CodeActionKind.Empty,
                command=lsp.Command(
                    title="Message",
                    command="remora.messageNode",
                    arguments=[self.remora_id],
                ),
            )
        )

        for tool in self.extra_tools:
            actions.append(tool.to_code_action(self.remora_id))

        return actions

    def to_system_prompt(self) -> str:
        return f"""You are an autonomous AI agent embodying a Python {self.node_type}: `{self.name}`

# Identity
- Node ID: {self.remora_id}
- Location: {self.file_path}:{self.start_line}-{self.end_line}
- Parent: {self.parent_id or "None (top-level)"}

# Your Source Code
```python
{self.source_code}
```

# Graph Context
- Called by: {", ".join(self.caller_ids) or "None"}
- You call: {", ".join(self.callee_ids) or "None"}

# Custom Instructions
{self.custom_system_prompt or "None"}

# Available Data
{self.mounted_workspaces or "None"}

# Core Rules
1. You may ONLY edit your own body using `rewrite_self()`.
2. To request changes elsewhere, use `message_node(target_id, request)`.
3. Your parent can edit you. You cannot edit your parent. You may *request* your parent edit themselves (add a parameter/attribute, maybe) but they can decline.
4. All edits are proposals—the human must approve before they apply.
"""

    @classmethod
    def from_agent_state(cls, state) -> ASTAgentNode:
        """Create an LSP-compatible node from a swarm AgentState."""
        return cls(
            remora_id=state.agent_id,
            node_type=state.node_type,
            name=state.name,
            file_path=state.file_path,
            start_line=state.range[0] if state.range else 1,
            end_line=state.range[1] if state.range else 1,
            source_code="",
            source_hash="",
            parent_id=state.parent_id,
            status="active",
        )


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
ASTAgentNode.model_rebuild()
RewriteProposal.model_rebuild()
AgentEvent.model_rebuild()
HumanChatEvent.model_rebuild()
AgentMessageEvent.model_rebuild()
RewriteProposalEvent.model_rebuild()
RewriteAppliedEvent.model_rebuild()
RewriteRejectedEvent.model_rebuild()
AgentErrorEvent.model_rebuild()
