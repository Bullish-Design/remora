# Remora Neovim V2.1: LSP-Native Architecture

A complete rewrite where **LSP is the spine**. Neovim connects to Remora as a language server. Pydantic models are the bridge—they define both the agent structure AND the LSP protocol extensions.

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           NEOVIM                                        │
│                                                                         │
│   Built-in LSP Client ◄──────────────────────────────────────────────┐  │
│         │                                                            │  │
│         │ (standard LSP protocol)                                    │  │
│         │                                                            │  │
│         ▼                                                            │  │
│   ┌─────────────────┐    ┌─────────────────┐                        │  │
│   │ Code Actions    │    │ Code Lens       │   Thin Lua layer for   │  │
│   │ (agent tools)   │    │ (agent IDs)     │   UI polish only       │  │
│   └─────────────────┘    └─────────────────┘                        │  │
│   ┌─────────────────┐    ┌─────────────────┐                        │  │
│   │ Diagnostics     │    │ Hover           │                        │  │
│   │ (proposals)     │    │ (agent status)  │                        │  │
│   └─────────────────┘    └─────────────────┘                        │  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ stdio / TCP
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      REMORA LSP SERVER                                  │
│                         (Python)                                        │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                    pygls LSP Framework                          │    │
│  │                                                                 │    │
│  │  textDocument/hover ──────► AgentNode.to_hover()               │    │
│  │  textDocument/codeLens ───► AgentNode.to_code_lens()           │    │
│  │  textDocument/codeAction ─► AgentNode.tools → CodeAction[]     │    │
│  │  workspace/executeCommand ► Tool.execute() → WorkspaceEdit     │    │
│  │  textDocument/diagnostic ─► Proposals → Diagnostic[]           │    │
│  │  $/remora/events ─────────► SSE-style notifications            │    │
│  │                                                                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                    │                                    │
│                                    ▼                                    │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                 Pydantic Model Layer                            │    │
│  │                                                                 │    │
│  │   ASTAgentNode ◄───► LSP DocumentSymbol                        │    │
│  │   ExtensionNode ────► LSP CodeAction schemas                   │    │
│  │   RewriteProposal ──► LSP WorkspaceEdit + Diagnostic           │    │
│  │   AgentEvent ───────► LSP $/remora/event notification          │    │
│  │                                                                 │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                    │                                    │
│              ┌─────────────────────┼─────────────────────┐             │
│              ▼                     ▼                     ▼             │
│       ┌───────────┐         ┌───────────┐         ┌───────────┐       │
│       │ Watcher   │         │ Runner    │         │ Graph     │       │
│       │ (AST+IDs) │         │ (vLLM)    │         │ (Rustworkx)│       │
│       └───────────┘         └───────────┘         └───────────┘       │
│              │                     │                     │             │
│              └─────────────────────┼─────────────────────┘             │
│                                    ▼                                    │
│                            ┌─────────────┐                             │
│                            │   SQLite    │                             │
│                            └─────────────┘                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. The Pydantic-LSP Bridge

The key insight: **Pydantic models define the schema once, then export to both agent prompts AND LSP protocol structures.**

### 1a. Base Agent Node

```python
from pydantic import BaseModel, Field, computed_field
from lsprotocol import types as lsp
from typing import Literal

class ASTAgentNode(BaseModel):
    """
    The universal agent structure.

    This model serves THREE purposes:
    1. Database schema (SQLite storage)
    2. Agent prompt context (sent to vLLM)
    3. LSP protocol data (converted to LSP types)
    """

    # === Identity ===
    remora_id: str                                      # rm_a1b2c3d4
    node_type: Literal["function", "class", "method", "file"]
    name: str
    file_path: str
    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0

    # === Source ===
    source_code: str
    source_hash: str                                    # For change detection

    # === Graph ===
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # === Status ===
    status: Literal["active", "orphaned", "running", "pending_approval"] = "active"
    pending_proposal_id: str | None = None

    # === Extension Injection ===
    custom_system_prompt: str = ""
    mounted_workspaces: str = ""
    extra_tools: list["ToolSchema"] = Field(default_factory=list)

    # =========================================================================
    # LSP CONVERSIONS - The bridge between Remora and Neovim
    # =========================================================================

    def to_document_symbol(self) -> lsp.DocumentSymbol:
        """Convert to LSP DocumentSymbol for outline/breadcrumbs."""
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
            children=[],  # Populated by tree builder
        )

    def to_range(self) -> lsp.Range:
        """Convert to LSP Range."""
        return lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=self.start_col),
            end=lsp.Position(line=self.end_line - 1, character=self.end_col),
        )

    def to_code_lens(self) -> lsp.CodeLens:
        """Inline lens showing agent ID and status."""
        status_icon = {
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
                title=f"{status_icon[self.status]} {self.remora_id}",
                command="remora.selectAgent",
                arguments=[self.remora_id],
            ),
        )

    def to_hover(self, recent_events: list["AgentEvent"] = None) -> lsp.Hover:
        """Rich hover showing agent details."""
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
        """Generate code actions from available tools."""
        actions = []

        # Base tools always available
        actions.append(lsp.CodeAction(
            title="💬 Chat with this agent",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title="Chat",
                command="remora.chat",
                arguments=[self.remora_id],
            ),
        ))

        actions.append(lsp.CodeAction(
            title="✏️ Ask agent to rewrite itself",
            kind=lsp.CodeActionKind.RefactorRewrite,
            command=lsp.Command(
                title="Rewrite",
                command="remora.requestRewrite",
                arguments=[self.remora_id],
            ),
        ))

        actions.append(lsp.CodeAction(
            title="📤 Message another agent",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title="Message",
                command="remora.messageNode",
                arguments=[self.remora_id],
            ),
        ))

        # Extension tools (from .remora/models/)
        for tool in self.extra_tools:
            actions.append(tool.to_code_action(self.remora_id))

        return actions

    # =========================================================================
    # PROMPT GENERATION - For vLLM
    # =========================================================================

    def to_system_prompt(self) -> str:
        """Generate the system prompt for this agent."""
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
- Called by: {', '.join(self.caller_ids) or 'None'}
- You call: {', '.join(self.callee_ids) or 'None'}

# Custom Instructions
{self.custom_system_prompt or 'None'}

# Available Data
{self.mounted_workspaces or 'None'}

# Core Rules
1. You may ONLY edit your own body using `rewrite_self()`.
2. To request changes elsewhere, use `message_node(target_id, request)`.
3. Your parent can edit you. You cannot edit your parent. You may *request* your parent edit themselves (add a parameter/attribute, maybe) but they can decline.
4. All edits are proposals—the human must approve before they apply.
"""
```

### 1b. Tool Schema (Pydantic → LSP CodeAction)

```python
class ToolSchema(BaseModel):
    """
    Describes a tool available to an agent.
    Converts directly to LSP CodeAction with input parameters.
    """
    name: str
    description: str
    parameters: dict  # JSON Schema for arguments

    def to_code_action(self, agent_id: str) -> lsp.CodeAction:
        """Convert tool to LSP CodeAction."""
        return lsp.CodeAction(
            title=f"🔧 {self.name}",
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title=self.name,
                command="remora.executeTool",
                arguments=[agent_id, self.name, self.parameters],
            ),
        )

    def to_llm_tool(self) -> dict:
        """Convert to vLLM/OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }
```

### 1c. Rewrite Proposal (Agent Output → LSP WorkspaceEdit + Diagnostic)

```python
class RewriteProposal(BaseModel):
    """
    A proposed code change from an agent.
    Converts to both LSP WorkspaceEdit (for applying) and Diagnostic (for display).
    """
    proposal_id: str
    agent_id: str
    file_path: str
    old_source: str
    new_source: str
    start_line: int
    end_line: int
    reasoning: str = ""

    @computed_field
    @property
    def diff(self) -> str:
        """Unified diff of the change."""
        import difflib
        return "\n".join(difflib.unified_diff(
            self.old_source.splitlines(),
            self.new_source.splitlines(),
            lineterm="",
        ))

    def to_workspace_edit(self) -> lsp.WorkspaceEdit:
        """Convert to LSP WorkspaceEdit for applying the change."""
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
        """Convert to LSP Diagnostic for showing in editor."""
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
        """Code actions to approve/reject this proposal."""
        return [
            lsp.CodeAction(
                title="✅ Accept rewrite",
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
                title="❌ Reject with feedback",
                kind=lsp.CodeActionKind.QuickFix,
                diagnostics=[self.to_diagnostic()],
                command=lsp.Command(
                    title="Reject",
                    command="remora.rejectProposal",
                    arguments=[self.proposal_id],
                ),
            ),
        ]
```

---

## 2. LSP Server Implementation

Using `pygls` (Python LSP framework), we implement a full language server where Remora features map to standard LSP capabilities.

### 2a. Server Setup

```python
from pygls.server import LanguageServer
from lsprotocol import types as lsp

class RemoraLanguageServer(LanguageServer):
    def __init__(self):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()           # SQLite
        self.graph = LazyGraph()        # Rustworkx
        self.watcher = ASTWatcher()     # Tree-sitter
        self.runner = AgentRunner()     # vLLM execution
        self.proposals: dict[str, RewriteProposal] = {}

server = RemoraLanguageServer()
```

### 2b. Document Synchronization

```python
@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: lsp.DidOpenTextDocumentParams):
    """Parse file and register all agent nodes."""
    uri = params.text_document.uri
    text = params.text_document.text

    nodes = server.watcher.parse_and_inject_ids(uri, text)
    server.db.upsert_nodes(nodes)
    server.db.update_edges(nodes)

    # Publish code lenses for all agents
    await publish_code_lenses(uri, nodes)

    # Publish any pending proposals as diagnostics
    proposals = server.db.get_proposals_for_file(uri)
    await publish_diagnostics(uri, proposals)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: lsp.DidSaveTextDocumentParams):
    """Re-parse on save, preserve IDs, update topology."""
    uri = params.text_document.uri
    text = Path(uri_to_path(uri)).read_text()

    old_nodes = server.db.get_nodes_for_file(uri)
    new_nodes = server.watcher.parse_and_inject_ids(uri, text, old_nodes)

    # Orphan detection
    old_by_key = {(n.name, n.node_type): n for n in old_nodes}
    for node in new_nodes:
        key = (node.name, node.node_type)
        if key in old_by_key:
            node.remora_id = old_by_key[key].remora_id
            del old_by_key[key]

    for orphan in old_by_key.values():
        server.db.set_status(orphan.remora_id, "orphaned")

    server.db.upsert_nodes(new_nodes)
    server.db.update_edges(new_nodes)

    # Signal graph invalidation
    server.graph.invalidate(uri)

    # Refresh UI
    await publish_code_lenses(uri, new_nodes)
```

### 2c. Hover (Agent Details)

```python
@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    """Show agent details on hover."""
    uri = params.text_document.uri
    pos = params.position

    node = server.db.get_node_at_position(uri, pos.line + 1, pos.character)
    if not node:
        return None

    agent = ASTAgentNode(**node)
    events = server.db.get_recent_events(agent.remora_id, limit=5)

    return agent.to_hover(events)
```

### 2d. Code Lens (Inline Agent IDs)

```python
@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    """Show agent IDs inline on definition lines."""
    uri = params.text_document.uri
    nodes = server.db.get_nodes_for_file(uri)

    return [ASTAgentNode(**n).to_code_lens() for n in nodes]
```

### 2e. Code Actions (Agent Tools)

```python
@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    """Provide agent tools as code actions."""
    uri = params.text_document.uri
    range_ = params.range

    # Get agent at cursor
    node = server.db.get_node_at_position(
        uri, range_.start.line + 1, range_.start.character
    )
    if not node:
        return []

    agent = ASTAgentNode(**node)
    actions = agent.to_code_actions()

    # Add proposal actions if there's a pending proposal
    if agent.pending_proposal_id:
        proposal = server.proposals.get(agent.pending_proposal_id)
        if proposal:
            actions.extend(proposal.to_code_actions())

    return actions
```

### 2f. Execute Command (Tool Dispatch)

```python
@server.feature(lsp.WORKSPACE_EXECUTE_COMMAND)
async def execute_command(params: lsp.ExecuteCommandParams) -> Any:
    """Handle Remora commands from code actions."""
    cmd = params.command
    args = params.arguments or []

    match cmd:
        case "remora.chat":
            agent_id = args[0]
            # Trigger input prompt via client
            await server.send_notification(
                "$/remora/requestInput",
                {"agent_id": agent_id, "prompt": "Message to agent:"}
            )

        case "remora.requestRewrite":
            agent_id = args[0]
            await server.send_notification(
                "$/remora/requestInput",
                {"agent_id": agent_id, "prompt": "What should this code do?"}
            )

        case "remora.executeTool":
            agent_id, tool_name, params = args
            await execute_agent_tool(agent_id, tool_name, params)

        case "remora.acceptProposal":
            proposal_id = args[0]
            proposal = server.proposals[proposal_id]

            # Apply the edit
            await server.apply_edit(lsp.ApplyWorkspaceEditParams(
                edit=proposal.to_workspace_edit()
            ))

            # Clean up
            del server.proposals[proposal_id]
            agent = server.db.get_node(proposal.agent_id)
            server.db.set_status(agent.remora_id, "active")
            server.db.clear_pending_proposal(agent.remora_id)

            # Emit event
            await emit_event(RewriteAppliedEvent(
                agent_id=proposal.agent_id,
                proposal_id=proposal_id
            ))

        case "remora.rejectProposal":
            proposal_id = args[0]
            # Request feedback
            await server.send_notification(
                "$/remora/requestInput",
                {"proposal_id": proposal_id, "prompt": "Feedback for agent:"}
            )

        case "remora.selectAgent":
            agent_id = args[0]
            # Could open a sidepanel or focus
            await server.send_notification(
                "$/remora/agentSelected",
                {"agent_id": agent_id}
            )
```

### 2g. Diagnostics (Pending Proposals)

```python
async def publish_diagnostics(uri: str, proposals: list[RewriteProposal]):
    """Publish pending proposals as diagnostics."""
    diagnostics = [p.to_diagnostic() for p in proposals]

    server.publish_diagnostics(lsp.PublishDiagnosticsParams(
        uri=uri,
        diagnostics=diagnostics
    ))
```

### 2h. Custom Notifications (Event Stream)

```python
# Custom LSP notifications for Remora-specific events
# These extend the protocol for real-time updates

@server.feature("$/remora/submitInput")
async def on_input_submitted(params: dict):
    """Handle user input from Neovim UI."""
    if "agent_id" in params:
        # Chat message
        agent_id = params["agent_id"]
        message = params["input"]

        correlation_id = generate_correlation_id()
        await emit_event(HumanChatEvent(
            to_agent=agent_id,
            message=message,
            correlation_id=correlation_id
        ))

        # Trigger agent execution
        await server.runner.trigger(agent_id, correlation_id)

    elif "proposal_id" in params:
        # Rejection feedback
        proposal_id = params["proposal_id"]
        feedback = params["input"]
        proposal = server.proposals[proposal_id]

        await emit_event(RewriteRejectedEvent(
            agent_id=proposal.agent_id,
            proposal_id=proposal_id,
            feedback=feedback
        ))

        # Re-trigger agent with feedback
        await server.runner.trigger(
            proposal.agent_id,
            proposal.correlation_id,
            context={"rejection_feedback": feedback}
        )


async def emit_event(event: BaseEvent):
    """Emit event to storage and notify client."""
    server.db.store_event(event)

    # Notify Neovim via custom LSP notification
    await server.send_notification("$/remora/event", event.model_dump())
```

---

## 3. Agent Execution

### 3a. The Runner Loop

```python
class AgentRunner:
    def __init__(self, server: RemoraLanguageServer):
        self.server = server
        self.llm = vLLMClient()
        self.queue = asyncio.Queue()

    async def run_forever(self):
        """Main execution loop."""
        while True:
            trigger = await self.queue.get()
            await self.execute_turn(trigger)

    async def trigger(self, agent_id: str, correlation_id: str, context: dict = None):
        """Queue an agent for execution."""
        # Cycle detection
        chain = self.server.db.get_activation_chain(correlation_id)

        if len(chain) >= MAX_CHAIN_DEPTH:
            await self.emit_error(agent_id, "Max activation depth exceeded", correlation_id)
            return

        if agent_id in [e.agent_id for e in chain]:
            await self.emit_error(agent_id, "Cycle detected in activation chain", correlation_id)
            return

        await self.queue.put(Trigger(
            agent_id=agent_id,
            correlation_id=correlation_id,
            context=context or {}
        ))

    async def execute_turn(self, trigger: Trigger):
        """Execute a single agent turn."""
        agent_id = trigger.agent_id
        correlation_id = trigger.correlation_id

        # Update status
        self.server.db.set_status(agent_id, "running")
        await self.refresh_code_lens(agent_id)

        # Record activation
        self.server.db.add_to_chain(correlation_id, agent_id)

        # Hydrate agent
        node = self.server.db.get_node(agent_id)
        agent = ASTAgentNode(**node)
        agent = self.apply_extensions(agent)

        # Build messages
        messages = [
            {"role": "system", "content": agent.to_system_prompt()},
        ]

        # Add triggering context
        events = self.server.db.get_events_for_correlation(correlation_id)
        for event in events:
            if isinstance(event, HumanChatEvent) and event.to_agent == agent_id:
                messages.append({"role": "user", "content": event.message})
            elif isinstance(event, AgentMessageEvent) and event.to_agent == agent_id:
                messages.append({"role": "user", "content": f"[From {event.from_agent}]: {event.message}"})

        if trigger.context.get("rejection_feedback"):
            messages.append({"role": "user", "content": f"[Feedback on rejected proposal]: {trigger.context['rejection_feedback']}"})

        # Build tools
        tools = self.get_agent_tools(agent)

        # Execute LLM call
        try:
            response = await self.llm.chat(messages, tools)
            await self.handle_response(agent, response, correlation_id)
        except Exception as e:
            await self.emit_error(agent_id, str(e), correlation_id)
        finally:
            self.server.db.set_status(agent_id, "active")
            await self.refresh_code_lens(agent_id)

    async def handle_response(self, agent: ASTAgentNode, response, correlation_id: str):
        """Process LLM response and tool calls."""
        for tool_call in response.tool_calls:
            match tool_call.name:
                case "rewrite_self":
                    new_source = tool_call.arguments["new_source"]
                    await self.create_proposal(agent, new_source, correlation_id)

                case "message_node":
                    target_id = tool_call.arguments["target_id"]
                    message = tool_call.arguments["message"]
                    await self.message_node(agent.remora_id, target_id, message, correlation_id)

                case "read_node":
                    target_id = tool_call.arguments["target_id"]
                    target = self.server.db.get_node(target_id)
                    # Return source to agent for continued processing
                    # (would need tool result handling)

                case _:
                    # Extension tool
                    await self.execute_extension_tool(agent, tool_call, correlation_id)

    async def create_proposal(self, agent: ASTAgentNode, new_source: str, correlation_id: str):
        """Create a rewrite proposal and notify client."""
        proposal = RewriteProposal(
            proposal_id=generate_id(),
            agent_id=agent.remora_id,
            file_path=agent.file_path,
            old_source=agent.source_code,
            new_source=new_source,
            start_line=agent.start_line,
            end_line=agent.end_line,
        )

        self.server.proposals[proposal.proposal_id] = proposal
        self.server.db.set_pending_proposal(agent.remora_id, proposal.proposal_id)
        self.server.db.set_status(agent.remora_id, "pending_approval")

        # Publish as diagnostic
        await publish_diagnostics(agent.file_path, [proposal])

        # Refresh code lens to show pending status
        await self.refresh_code_lens(agent.remora_id)

        # Emit event
        await emit_event(RewriteProposalEvent(
            agent_id=agent.remora_id,
            proposal_id=proposal.proposal_id,
            diff=proposal.diff,
            correlation_id=correlation_id
        ))

    async def message_node(self, from_id: str, to_id: str, message: str, correlation_id: str):
        """Send message between agents."""
        await emit_event(AgentMessageEvent(
            from_agent=from_id,
            to_agent=to_id,
            message=message,
            correlation_id=correlation_id
        ))

        # Trigger target agent
        await self.trigger(to_id, correlation_id)
```

### 3b. Extension Discovery

```python
def apply_extensions(self, agent: ASTAgentNode) -> ASTAgentNode:
    """Find and apply matching extension nodes."""
    extensions = load_extensions_from_disk()  # .remora/models/*.py

    for ext_cls in extensions:
        if ext_cls.matches(agent.node_type, agent.name):
            ext = ext_cls()
            agent.custom_system_prompt = ext.system_prompt
            agent.mounted_workspaces = ext.get_workspaces()
            agent.extra_tools = ext.get_tool_schemas()
            break

    return agent


def load_extensions_from_disk() -> list[type]:
    """Load ExtensionNode subclasses from .remora/models/"""
    extensions = []
    models_dir = Path(".remora/models")

    if not models_dir.exists():
        return extensions

    for py_file in models_dir.glob("*.py"):
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for name, obj in module.__dict__.items():
            if (isinstance(obj, type) and
                issubclass(obj, ExtensionNode) and
                obj is not ExtensionNode):
                extensions.append(obj)

    return extensions
```

---

## 4. Neovim Client (Minimal Lua)

Because we're using native LSP, Neovim needs minimal custom code. Most features work via standard LSP client.

### 4a. Setup

```lua
-- lua/remora/init.lua
local M = {}

function M.setup(opts)
    opts = opts or {}

    -- Register Remora as a language server
    vim.lsp.config["remora"] = {
        cmd = { "remora", "lsp" },  -- or { "python", "-m", "remora.lsp" }
        filetypes = { "python" },    -- expand as needed
        root_markers = { ".remora", ".git" },
        settings = {},
    }

    -- Enable for Python files
    vim.lsp.enable("remora")

    -- Handle custom notifications
    vim.lsp.handlers["$/remora/event"] = M.on_event
    vim.lsp.handlers["$/remora/requestInput"] = M.on_request_input
    vim.lsp.handlers["$/remora/agentSelected"] = M.on_agent_selected
end

return M
```

### 4b. Event Handling

```lua
-- lua/remora/init.lua (continued)

function M.on_event(err, result, ctx)
    local event = result

    -- Update statusline or notify
    if event.event_type == "RewriteProposalEvent" then
        vim.notify(
            string.format("Agent %s proposes rewrite", event.agent_id),
            vim.log.levels.INFO
        )
    elseif event.event_type == "AgentErrorEvent" then
        vim.notify(
            string.format("Agent error: %s", event.error),
            vim.log.levels.ERROR
        )
    end

    -- Could update a sidepanel here
    if M.sidepanel then
        M.sidepanel.add_event(event)
    end
end

function M.on_request_input(err, result, ctx)
    local prompt = result.prompt
    local agent_id = result.agent_id
    local proposal_id = result.proposal_id

    vim.ui.input({ prompt = prompt }, function(input)
        if input then
            -- Send back to server
            vim.lsp.buf_notify(0, "$/remora/submitInput", {
                agent_id = agent_id,
                proposal_id = proposal_id,
                input = input
            })
        end
    end)
end

function M.on_agent_selected(err, result, ctx)
    local agent_id = result.agent_id
    -- Could open sidepanel or focus
    M.show_agent_panel(agent_id)
end
```

### 4c. Commands

```lua
-- lua/remora/init.lua (continued)

function M.setup_commands()
    vim.api.nvim_create_user_command("RemoraChat", function()
        -- Get agent at cursor via code action
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.chat"
            end,
            apply = true
        })
    end, {})

    vim.api.nvim_create_user_command("RemoraRewrite", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.requestRewrite"
            end,
            apply = true
        })
    end, {})

    vim.api.nvim_create_user_command("RemoraAccept", function()
        -- Accept proposal from diagnostic at cursor
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command and action.command.command == "remora.acceptProposal"
            end,
            apply = true
        })
    end, {})
end
```

### 4d. What You Get For Free (Standard LSP)

| Feature | LSP Method | Works Out of Box |
|---------|------------|------------------|
| Agent IDs inline | `textDocument/codeLens` | ✅ |
| Hover for details | `textDocument/hover` | ✅ |
| Tool menu | `textDocument/codeAction` | ✅ |
| Pending proposals | `textDocument/publishDiagnostics` | ✅ |
| Apply rewrites | `workspace/applyEdit` | ✅ |
| Document symbols | `textDocument/documentSymbol` | ✅ |

---

## 5. Graph & Cycle Detection

### 5a. SQLite Schema

```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    start_col INTEGER DEFAULT 0,
    end_col INTEGER DEFAULT 0,
    source_code TEXT,
    source_hash TEXT,
    status TEXT DEFAULT 'active',
    pending_proposal_id TEXT,
    parent_id TEXT REFERENCES nodes(id)
);

CREATE TABLE edges (
    from_id TEXT NOT NULL REFERENCES nodes(id),
    to_id TEXT NOT NULL REFERENCES nodes(id),
    edge_type TEXT NOT NULL,  -- parent_of, calls, imports
    PRIMARY KEY (from_id, to_id, edge_type)
);

CREATE TABLE activation_chain (
    correlation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    PRIMARY KEY (correlation_id, agent_id)
);

CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    correlation_id TEXT,
    agent_id TEXT,
    payload JSON NOT NULL
);

CREATE TABLE proposals (
    proposal_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES nodes(id),
    old_source TEXT NOT NULL,
    new_source TEXT NOT NULL,
    diff TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, accepted, rejected
    created_at REAL NOT NULL
);

CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_events_correlation ON events(correlation_id);
CREATE INDEX idx_events_agent ON events(agent_id);
CREATE INDEX idx_chain_correlation ON activation_chain(correlation_id);
```

### 5b. Rustworkx Lazy Loading

```python
class LazyGraph:
    def __init__(self, db: RemoraDB):
        self.db = db
        self.graph = rx.PyDiGraph()
        self.node_indices: dict[str, int] = {}
        self.loaded_files: set[str] = set()

    def invalidate(self, file_path: str):
        """Mark file as needing reload."""
        self.loaded_files.discard(file_path)

    def ensure_loaded(self, node_id: str):
        """Lazy load node's neighborhood."""
        if node_id in self.node_indices:
            return

        # Get node and its neighborhood from SQLite
        node = self.db.get_node(node_id)
        if not node:
            return

        # Load 2-hop neighborhood
        neighbors = self.db.get_neighborhood(node_id, depth=2)

        for n in neighbors:
            if n.id not in self.node_indices:
                idx = self.graph.add_node(n)
                self.node_indices[n.id] = idx

        # Load edges
        edges = self.db.get_edges_for_nodes([n.id for n in neighbors])
        for edge in edges:
            if edge.from_id in self.node_indices and edge.to_id in self.node_indices:
                self.graph.add_edge(
                    self.node_indices[edge.from_id],
                    self.node_indices[edge.to_id],
                    edge.edge_type
                )

    def get_parent(self, node_id: str) -> str | None:
        """Get parent node ID."""
        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return None

        idx = self.node_indices[node_id]
        parents = self.graph.predecessor_indices(idx)

        for p_idx in parents:
            edge = self.graph.get_edge_data(p_idx, idx)
            if edge == "parent_of":
                return self.graph[p_idx].id

        return None

    def get_callers(self, node_id: str) -> list[str]:
        """Get nodes that call this one."""
        self.ensure_loaded(node_id)
        if node_id not in self.node_indices:
            return []

        idx = self.node_indices[node_id]
        callers = []

        for p_idx in self.graph.predecessor_indices(idx):
            edge = self.graph.get_edge_data(p_idx, idx)
            if edge == "calls":
                callers.append(self.graph[p_idx].id)

        return callers
```

---

## 6. ID Management

### 6a. ID Format

```
# rm_a1b2c3d4
```

- Prefix: `rm_` (8 chars total including underscore)
- Body: 8 lowercase alphanumeric characters
- Always at end of definition line

### 6b. ID Injection

```python
def inject_ids(file_path: Path, nodes: list[ASTAgentNode]) -> str:
    """Inject/update remora IDs in source file."""
    lines = file_path.read_text().splitlines()

    # Sort by line number descending (so line numbers don't shift)
    nodes_sorted = sorted(nodes, key=lambda n: n.start_line, reverse=True)

    for node in nodes_sorted:
        line_idx = node.start_line - 1
        line = lines[line_idx]

        # Remove existing remora ID if present
        line = re.sub(r'\s*# rm_[a-z0-9]{8}\s*$', '', line)

        # Add new ID
        lines[line_idx] = f"{line}  # {node.remora_id}"

    new_content = "\n".join(lines) + "\n"
    file_path.write_text(new_content)
    return new_content
```

### 6c. File-Level IDs

```python
# remora-file: rm_xyz12345
"""This module handles configuration loading."""

class ConfigLoader:  # rm_a1b2c3d4
    ...
```

First line of file (or after shebang/encoding) gets the file-level ID.

---

## 7. MVP Implementation Order

### Phase 1: LSP Foundation
- [ ] `pygls` server skeleton
- [ ] SQLite schema + basic queries
- [ ] Tree-sitter parsing + ID injection
- [ ] `textDocument/didOpen` and `didSave`
- [ ] `textDocument/codeLens` for agent IDs
- [ ] `textDocument/hover` for agent details

### Phase 2: Proposals
- [ ] `textDocument/codeAction` for tools
- [ ] `workspace/executeCommand` dispatch
- [ ] `RewriteProposal` → Diagnostic + CodeAction
- [ ] `workspace/applyEdit` for accepting proposals
- [ ] Custom notification for input prompts

### Phase 3: Agent Execution
- [ ] Agent hydration from DB
- [ ] vLLM integration
- [ ] `rewrite_self` tool implementation
- [ ] Activation chain + cycle detection
- [ ] Event storage + correlation IDs

### Phase 4: Communication
- [ ] `message_node` tool
- [ ] Inter-agent triggering
- [ ] Graph lazy loading (Rustworkx)
- [ ] `read_node` tool

### Phase 5: Extensions
- [ ] `.remora/models/` discovery
- [ ] Extension → tool schema conversion
- [ ] Custom tools in code actions

---

## 8. File Structure

```
remora/
├── lsp/
│   ├── __main__.py           # Entry: python -m remora.lsp
│   ├── server.py             # RemoraLanguageServer
│   ├── handlers/
│   │   ├── documents.py      # didOpen, didSave, didClose
│   │   ├── hover.py          # textDocument/hover
│   │   ├── lens.py           # textDocument/codeLens
│   │   ├── actions.py        # textDocument/codeAction
│   │   └── commands.py       # workspace/executeCommand
│   └── notifications.py      # Custom $/remora/* handlers
├── core/
│   ├── models.py             # ASTAgentNode, RewriteProposal, etc.
│   ├── db.py                 # SQLite operations
│   ├── graph.py              # Rustworkx lazy graph
│   ├── watcher.py            # Tree-sitter parsing + ID injection
│   └── events.py             # Event types
├── agent/
│   ├── runner.py             # AgentRunner execution loop
│   ├── tools.py              # Built-in tool implementations
│   ├── extensions.py         # ExtensionNode base + discovery
│   └── llm.py                # vLLM client
└── nvim/
    └── lua/
        └── remora/
            ├── init.lua      # Setup + LSP config
            ├── handlers.lua  # Custom notification handlers
            └── panel.lua     # Optional sidepanel UI
```

---

## Summary

The LSP-native architecture means:

1. **Neovim does almost nothing custom.** Standard LSP client handles 90% of the UX.
2. **Pydantic models are the single source of truth.** They define storage, prompts, AND protocol structures.
3. **Features map to LSP primitives:**
   - Agent IDs → CodeLens
   - Agent details → Hover
   - Agent tools → CodeAction
   - Pending proposals → Diagnostics + QuickFix
   - Apply changes → WorkspaceEdit
4. **Custom notifications** (`$/remora/*`) handle real-time events and input prompts.
5. **The Lua layer** is purely for polish—handling custom notifications, optional sidepanel, keybindings.

This is the tightest possible integration. Remora becomes a language server that happens to run AI agents.

---

## Appendix A: Nui-Components UI Examples

While LSP handles 90% of the integration, `nui-components.nvim` provides the rich, application-like UI layer for complex interactions. This appendix shows how to build reactive sidebars that respond to agent events.

### A1. The Collapsible Sidebar

Using the Flexbox engine, the UI can have multiple states:

**Collapsed (Narrow Mode):** A 3-4 column wide vertical strip on the far right showing agent status icons.

**Expanded (Chat/Info Mode):** When expanded, reveals tabs for State, Subscriptions, and Chat input.

```lua
-- lua/remora/panel.lua
local n = require("nui-components")
local Signal = require("nui-components.signal")

local M = {}

-- Reactive state
M.state = Signal.create({
    expanded = false,
    width = 4,
    selected_agent = nil,
    agents = {},           -- { [id] = { status = "active", name = "..." } }
    events = {},           -- Recent events for selected agent
    border_hl = "FloatBorder",
})

function M.create_panel()
    local state = M.state

    return n.rows(
        -- Dynamic width based on expanded state
        n.columns(
            { flex = 0, size = function() return state.expanded:get() and 40 or 4 end },

            -- Collapsed view: just status icons
            n.if_(
                function() return not state.expanded:get() end,
                n.rows(
                    n.each(state.agents, function(agent)
                        return n.text({
                            content = M.status_icon(agent.status),
                            hl_group = M.status_hl(agent.status),
                            on_click = function()
                                state.selected_agent:set(agent.id)
                                state.expanded:set(true)
                            end,
                        })
                    end)
                )
            ),

            -- Expanded view: full agent details
            n.if_(
                function() return state.expanded:get() end,
                n.rows(
                    -- Header with agent info
                    M.agent_header(state),

                    -- Tabs
                    n.tabs({
                        n.tab({ label = "State" }, M.state_tab(state)),
                        n.tab({ label = "Events" }, M.events_tab(state)),
                        n.tab({ label = "Chat" }, M.chat_tab(state)),
                    }),

                    -- Footer with keybindings
                    n.text({
                        content = "[q]uit  [c]hat  [r]efresh",
                        hl_group = "Comment",
                    })
                )
            )
        ),

        -- Border color bound to reactive state
        {
            border = {
                style = "rounded",
                hl_group = function() return state.border_hl:get() end,
            },
        }
    )
end

function M.status_icon(status)
    local icons = {
        active = "●",
        running = "▶",
        pending_approval = "⏸",
        orphaned = "○",
        grail_triggered = "★",
    }
    return icons[status] or "?"
end

function M.status_hl(status)
    local hls = {
        active = "DiagnosticOk",
        running = "DiagnosticInfo",
        pending_approval = "DiagnosticWarn",
        orphaned = "Comment",
        grail_triggered = "Special",
    }
    return hls[status] or "Normal"
end

return M
```

### A2. The Agent Header Component

```lua
function M.agent_header(state)
    return n.rows(
        n.text({
            content = function()
                local agent = state.selected_agent:get()
                if not agent then return "No agent selected" end
                return string.format("## %s", agent.name)
            end,
            hl_group = "Title",
        }),

        n.text({
            content = function()
                local agent = state.selected_agent:get()
                if not agent then return "" end
                return string.format("ID: %s | %s", agent.id, agent.status)
            end,
            hl_group = function()
                local agent = state.selected_agent:get()
                return agent and M.status_hl(agent.status) or "Normal"
            end,
        }),

        n.separator(),

        -- Graph context
        n.text({
            content = function()
                local agent = state.selected_agent:get()
                if not agent then return "" end
                return string.format("Parent: %s", agent.parent_id or "None")
            end,
            hl_group = "Comment",
        })
    )
end
```

### A3. The Events Tab with Live Updates

```lua
function M.events_tab(state)
    return n.rows(
        n.scroll({
            max_height = 15,
            content = n.each(state.events, function(event)
                return n.rows(
                    n.columns(
                        n.text({
                            content = M.event_icon(event.event_type),
                            hl_group = M.event_hl(event.event_type),
                            flex = 0,
                            size = 3,
                        }),
                        n.text({
                            content = event.summary or event.event_type,
                            flex = 1,
                        }),
                        n.text({
                            content = M.format_time(event.timestamp),
                            hl_group = "Comment",
                            flex = 0,
                            size = 8,
                        })
                    ),

                    -- Expandable details for proposals
                    n.if_(
                        function() return event.event_type == "RewriteProposalEvent" end,
                        n.box({
                            border = "single",
                            content = n.text({
                                content = event.diff or "",
                                hl_group = "DiffText",
                            }),
                        })
                    )
                )
            end)
        })
    )
end

function M.event_icon(event_type)
    local icons = {
        AgentStartEvent = "▶",
        AgentCompleteEvent = "✓",
        AgentErrorEvent = "✗",
        RewriteProposalEvent = "✎",
        RewriteAppliedEvent = "✓",
        AgentMessageEvent = "◆",
        HumanChatEvent = "◇",
    }
    return icons[event_type] or "•"
end
```

### A4. The Chat Tab with Input

```lua
function M.chat_tab(state)
    local input_value = Signal.create("")

    return n.rows(
        -- Message history
        n.scroll({
            max_height = 10,
            content = n.each(state.events, function(event)
                if event.event_type ~= "HumanChatEvent" and
                   event.event_type ~= "AgentMessageEvent" then
                    return nil
                end

                local is_human = event.event_type == "HumanChatEvent"
                return n.box({
                    border = is_human and "rounded" or "single",
                    hl_group = is_human and "Normal" or "Comment",
                    content = n.text({ content = event.message }),
                })
            end)
        }),

        n.separator(),

        -- Input field
        n.input({
            placeholder = "Message agent...",
            value = input_value,
            on_submit = function(value)
                if value and value ~= "" then
                    local agent = state.selected_agent:get()
                    if agent then
                        -- Send via LSP notification
                        vim.lsp.buf_notify(0, "$/remora/submitInput", {
                            agent_id = agent.id,
                            input = value,
                        })
                        input_value:set("")
                    end
                end
            end,
        })
    )
end
```

### A5. SSE Event Subscription (The Grail Trigger)

```lua
-- lua/remora/sse.lua
local M = {}
local Signal = require("nui-components.signal")
local panel = require("remora.panel")

function M.subscribe()
    -- Background job reading SSE stream
    local job_id = vim.fn.jobstart({
        "curl", "-N", "-s",
        "http://localhost:7777/events/stream"
    }, {
        on_stdout = function(_, data)
            for _, line in ipairs(data) do
                if line:match("^data: ") then
                    local json_str = line:sub(7)
                    local ok, event = pcall(vim.json.decode, json_str)
                    if ok then
                        M.handle_event(event)
                    end
                end
            end
        end,
        on_exit = function(_, code)
            if code ~= 0 then
                vim.schedule(function()
                    vim.notify("SSE connection lost, reconnecting...", vim.log.levels.WARN)
                    vim.defer_fn(M.subscribe, 3000)
                end)
            end
        end,
    })

    return job_id
end

function M.handle_event(event)
    local state = panel.state

    -- Update agent status
    if event.agent_id then
        local agents = state.agents:get()
        if agents[event.agent_id] then
            if event.event_type == "AgentStartEvent" then
                agents[event.agent_id].status = "running"
            elseif event.event_type == "AgentCompleteEvent" then
                agents[event.agent_id].status = "active"
            elseif event.event_type == "RewriteProposalEvent" then
                agents[event.agent_id].status = "pending_approval"
            end
            state.agents:set(agents)
        end
    end

    -- Check for Grail trigger (special high-priority event)
    if M.is_grail_trigger(event) then
        -- Flash the border gold
        state.border_hl:set("GrailBorder")

        -- Also send a notification
        vim.schedule(function()
            vim.notify(
                string.format("⚡ Grail Event: %s", event.summary or event.event_type),
                vim.log.levels.INFO,
                { title = "Remora" }
            )
        end)

        -- Reset border after 3 seconds
        vim.defer_fn(function()
            state.border_hl:set("FloatBorder")
        end, 3000)
    end

    -- Add to events list for selected agent
    local selected = state.selected_agent:get()
    if selected and event.agent_id == selected.id then
        local events = state.events:get()
        table.insert(events, 1, event)
        -- Keep only last 50 events
        while #events > 50 do
            table.remove(events)
        end
        state.events:set(events)
    end
end

function M.is_grail_trigger(event)
    -- Check for grail_trigger tag or specific event types
    if event.tags and vim.tbl_contains(event.tags, "grail_trigger") then
        return true
    end

    -- Major completions
    if event.event_type == "AgentCompleteEvent" and event.significance == "high" then
        return true
    end

    return false
end

return M
```

### A6. Highlight Groups Setup

```lua
-- lua/remora/highlights.lua
local M = {}

function M.setup()
    -- Grail trigger border (gold/purple pulse effect)
    vim.api.nvim_set_hl(0, "GrailBorder", {
        fg = "#FFD700",  -- Gold
        bold = true,
    })

    vim.api.nvim_set_hl(0, "GrailBorderAlt", {
        fg = "#8A2BE2",  -- Purple
        bold = true,
    })

    -- Agent status colors
    vim.api.nvim_set_hl(0, "RemoraActive", { fg = "#50fa7b" })
    vim.api.nvim_set_hl(0, "RemoraRunning", { fg = "#8be9fd" })
    vim.api.nvim_set_hl(0, "RemoraPending", { fg = "#ffb86c" })
    vim.api.nvim_set_hl(0, "RemoraOrphaned", { fg = "#6272a4" })
end

return M
```

### A7. Synergy: LSP + Nui-Components

The two technologies work in perfect harmony:

| Layer | Responsibility |
|-------|----------------|
| **LSP** | Code synchronization, diagnostics, hover states, code actions, workspace edits |
| **Nui-Components** | Rich application UI: chat interface, event streams, subscription trees, reactive visual feedback |
| **Node IDs** | The stable anchor linking LSP cursor position to the specific agent rendered in Nui |

**The interaction flow:**

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   LSP Hover     │     │  Code Action    │     │   Nui Panel     │
│   (Quick Info)  │────►│  (Open Agent)   │────►│  (Full UI)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                                               │
        │ rm_a1b2c3d4 (Node ID links them)             │
        └───────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SSE Stream    │────►│  Signal Update  │────►│  Border Flash   │
│  (Background)   │     │  (Reactive)     │     │  (Visual Alert) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Example: Grail Trigger Flow**

1. Background agent completes a major refactor (emits event with `grail_trigger` tag)
2. SSE pushes event to Neovim via `/events/stream`
3. Lua client parses event, updates `nui-components` Signal: `state.border_hl:set("GrailBorder")`
4. The panel border instantly changes from `#444444` grey to `#FFD700` gold
5. User notices the flash, hits `<leader>ra` to expand the sidebar
6. Full agent output and diff are visible in the Nui panel
7. User clicks Accept (or runs `:RemoraAccept`), which fires LSP code action
8. LSP applies the `WorkspaceEdit`, file updates in buffer
