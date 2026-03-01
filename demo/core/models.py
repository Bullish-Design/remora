import hashlib
import random
import string
import difflib
from pydantic import BaseModel, Field, computed_field
from lsprotocol import types as lsp
from typing import Literal


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

    def to_hover(self, recent_events: list["AgentEvent"] = None) -> lsp.Hover:
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
            for ev in recent_events[:5]:
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
4. All edits are proposals\u2014the human must approve before they apply.
"""


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


class HumanChatEvent(AgentEvent):
    to_agent: str = ""
    message: str = ""

    def __init__(self, **data):
        data["event_type"] = "HumanChatEvent"
        data["summary"] = f"Human message to {data.get('to_agent', '')}"
        super().__init__(**data)


class AgentMessageEvent(AgentEvent):
    from_agent: str = ""
    to_agent: str = ""
    message: str = ""

    def __init__(self, **data):
        data["event_type"] = "AgentMessageEvent"
        data["summary"] = f"Message from {data.get('from_agent', '')} to {data.get('to_agent', '')}"
        super().__init__(**data)


class RewriteProposalEvent(AgentEvent):
    proposal_id: str = ""
    diff: str = ""

    def __init__(self, **data):
        data["event_type"] = "RewriteProposalEvent"
        data["summary"] = f"Rewrite proposal from {data.get('agent_id', '')}"
        super().__init__(**data)


class RewriteAppliedEvent(AgentEvent):
    agent_id: str = ""
    proposal_id: str = ""

    def __init__(self, **data):
        data["event_type"] = "RewriteAppliedEvent"
        data["summary"] = f"Proposal {data.get('proposal_id', '')} accepted"
        super().__init__(**data)


class RewriteRejectedEvent(AgentEvent):
    agent_id: str = ""
    proposal_id: str = ""
    feedback: str = ""

    def __init__(self, **data):
        data["event_type"] = "RewriteRejectedEvent"
        data["summary"] = f"Proposal rejected with feedback"
        super().__init__(**data)


class AgentErrorEvent(AgentEvent):
    error: str = ""

    def __init__(self, **data):
        data["event_type"] = "AgentErrorEvent"
        data["summary"] = f"Error: {data.get('error', '')[:50]}"
        super().__init__(**data)
