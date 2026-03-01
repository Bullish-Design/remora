import asyncio
import uuid
from pathlib import Path
from typing import Any

from pygls.lsp.server import LanguageServer
from lsprotocol import types as lsp

from demo.core import (
    RemoraDB,
    LazyGraph,
    ASTWatcher,
    ASTAgentNode,
    RewriteProposal,
    HumanChatEvent,
    AgentMessageEvent,
    RewriteProposalEvent,
    RewriteAppliedEvent,
    RewriteRejectedEvent,
    AgentErrorEvent,
    generate_id,
)


MAX_CHAIN_DEPTH = 10


class RemoraLanguageServer(LanguageServer):
    def __init__(self):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()
        self.graph = LazyGraph(self.db)
        self.watcher = ASTWatcher()
        self.proposals: dict[str, RewriteProposal] = {}
        self.runner = None
        self._correlation_counter = 0

    def generate_correlation_id(self) -> str:
        self._correlation_counter += 1
        return f"corr_{self._correlation_counter}_{uuid.uuid4().hex[:8]}"


server = RemoraLanguageServer()


def uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        return uri[7:]
    return uri


async def publish_code_lenses(uri: str, nodes: list[ASTAgentNode]):
    lenses = [node.to_code_lens() for node in nodes]
    server.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[]))
    server.protocol.notify(
        "textDocument/codeLens", lsp.CodeLensParams(text_document=lsp.TextDocumentIdentifier(uri=uri))
    )


async def publish_diagnostics(uri: str, proposals: list[RewriteProposal]):
    diagnostics = [p.to_diagnostic() for p in proposals]
    server.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))


async def emit_event(event):
    event.timestamp = event.timestamp or asyncio.get_event_loop().time()
    server.db.store_event(event)
    server.protocol.notify("$/remora/event", event.model_dump())
    return event


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: lsp.DidOpenTextDocumentParams):
    uri = params.text_document.uri
    text = params.text_document.text

    nodes = server.watcher.parse_and_inject_ids(uri, text)
    server.db.upsert_nodes(nodes)
    server.db.update_edges(nodes)

    await publish_code_lenses(uri, nodes)

    proposals = server.db.get_proposals_for_file(uri)
    for p in proposals:
        proposal = RewriteProposal(
            proposal_id=p["proposal_id"],
            agent_id=p["agent_id"],
            file_path=p["node_file_path"],
            old_source=p["old_source"],
            new_source=p["new_source"],
            start_line=1,
            end_line=len(p["new_source"].splitlines()),
            reasoning="",
            correlation_id="",
        )
        server.proposals[p["proposal_id"]] = proposal

    await publish_diagnostics(uri, list(server.proposals.values()))


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: lsp.DidSaveTextDocumentParams):
    uri = params.text_document.uri
    text = Path(uri_to_path(uri)).read_text()

    old_nodes = server.db.get_nodes_for_file(uri)
    new_nodes = server.watcher.parse_and_inject_ids(uri, text, old_nodes)

    old_by_key = {(n["name"], n["node_type"]): n for n in old_nodes}
    for node in new_nodes:
        key = (node.name, node.node_type)
        if key in old_by_key:
            node.remora_id = old_by_key[key].remora_id
            del old_by_key[key]

    for orphan_key in old_by_key:
        orphan = old_by_key[orphan_key]
        server.db.set_status(orphan["id"], "orphaned")

    server.db.upsert_nodes(new_nodes)
    server.db.update_edges(new_nodes)

    server.graph.invalidate(uri)

    await publish_code_lenses(uri, new_nodes)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
async def did_close(params: lsp.DidCloseTextDocumentParams):
    pass


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    uri = params.text_document.uri
    pos = params.position

    node = server.db.get_node_at_position(uri, pos.line + 1, pos.character)
    if not node:
        return None

    agent = ASTAgentNode(**node)
    events = server.db.get_recent_events(agent.remora_id, limit=5)

    return agent.to_hover(events)


@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    uri = params.text_document.uri
    nodes = server.db.get_nodes_for_file(uri)

    return [ASTAgentNode(**n).to_code_lens() for n in nodes]


@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    uri = params.text_document.uri
    range_ = params.range

    node = server.db.get_node_at_position(uri, range_.start.line + 1, range_.start.character)
    if not node:
        return []

    agent = ASTAgentNode(**node)
    actions = agent.to_code_actions()

    if agent.pending_proposal_id:
        proposal = server.proposals.get(agent.pending_proposal_id)
        if proposal:
            actions.extend(proposal.to_code_actions())

    return actions


@server.feature(lsp.WORKSPACE_EXECUTE_COMMAND)
async def execute_command(params: lsp.ExecuteCommandParams) -> Any:
    cmd = params.command
    args = params.arguments or []

    match cmd:
        case "remora.chat":
            agent_id = args[0]
            server.protocol.notify("$/remora/requestInput", {"agent_id": agent_id, "prompt": "Message to agent:"})

        case "remora.requestRewrite":
            agent_id = args[0]
            server.protocol.notify(
                "$/remora/requestInput", {"agent_id": agent_id, "prompt": "What should this code do?"}
            )

        case "remora.executeTool":
            agent_id, tool_name, tool_params = args[0], args[1], args[2] if len(args) > 2 else {}
            if server.runner:
                await server.runner.execute_extension_tool(
                    agent_id, tool_name, tool_params, server.generate_correlation_id()
                )

        case "remora.acceptProposal":
            proposal_id = args[0]
            proposal = server.proposals.get(proposal_id)
            if not proposal:
                return

            await server.workspace_apply_edit(lsp.ApplyWorkspaceEditParams(edit=proposal.to_workspace_edit()))

            del server.proposals[proposal_id]
            agent = server.db.get_node(proposal.agent_id)
            if agent:
                server.db.set_status(agent["id"], "active")
                server.db.clear_pending_proposal(agent["id"])

            await emit_event(
                RewriteAppliedEvent(
                    agent_id=proposal.agent_id,
                    proposal_id=proposal_id,
                    correlation_id=proposal.correlation_id or "",
                )
            )

        case "remora.rejectProposal":
            proposal_id = args[0]
            server.protocol.notify(
                "$/remora/requestInput", {"proposal_id": proposal_id, "prompt": "Feedback for agent:"}
            )

        case "remora.selectAgent":
            agent_id = args[0]
            server.protocol.notify("$/remora/agentSelected", {"agent_id": agent_id})

        case _:
            pass


@server.feature("$/remora/submitInput")
async def on_input_submitted(params: dict):
    if "agent_id" in params:
        agent_id = params["agent_id"]
        message = params["input"]

        correlation_id = server.generate_correlation_id()
        await emit_event(HumanChatEvent(to_agent=agent_id, message=message, correlation_id=correlation_id))

        if server.runner:
            await server.runner.trigger(agent_id, correlation_id)

    elif "proposal_id" in params:
        proposal_id = params["proposal_id"]
        feedback = params["input"]
        proposal = server.proposals.get(proposal_id)

        if proposal:
            await emit_event(
                RewriteRejectedEvent(
                    agent_id=proposal.agent_id,
                    proposal_id=proposal_id,
                    feedback=feedback,
                    correlation_id=proposal.correlation_id or "",
                )
            )

            if server.runner:
                await server.runner.trigger(
                    proposal.agent_id, proposal.correlation_id, context={"rejection_feedback": feedback}
                )


def main():
    server.start_io()


if __name__ == "__main__":
    main()
