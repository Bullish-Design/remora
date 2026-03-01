# src/remora/lsp/server.py
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pygls.lsp.server import LanguageServer
from lsprotocol import types as lsp

from remora.lsp.models import (
    ASTAgentNode,
    RewriteProposal,
    HumanChatEvent,
    AgentMessageEvent,
    RewriteProposalEvent,
    RewriteAppliedEvent,
    RewriteRejectedEvent,
    AgentErrorEvent,
    ToolSchema,
    generate_id,
)
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.watcher import ASTWatcher, inject_ids

if TYPE_CHECKING:
    from remora.lsp.runner import AgentRunner

logger = logging.getLogger("remora.lsp")

MAX_CHAIN_DEPTH = 10


class RemoraLanguageServer(LanguageServer):
    def __init__(
        self,
        event_store=None,
        subscriptions=None,
        swarm_state=None,
    ):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()
        self.graph = LazyGraph(self.db)
        self.watcher = ASTWatcher()
        self.proposals: dict[str, RewriteProposal] = {}
        self.runner: "AgentRunner | None" = None
        self._correlation_counter = 0
        self._injecting: set[str] = set()
        self.event_store = event_store
        self.subscriptions = subscriptions
        self.swarm_state = swarm_state

    def generate_correlation_id(self) -> str:
        self._correlation_counter += 1
        return f"corr_{self._correlation_counter}_{uuid.uuid4().hex[:8]}"


server = RemoraLanguageServer()


def uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        return uri[7:]
    return uri


async def refresh_code_lenses() -> None:
    """Ask the client to re-request code lenses."""
    try:
        await server.workspace_code_lens_refresh_async()
    except Exception:
        pass


async def publish_diagnostics(uri: str, proposals: list[RewriteProposal]) -> None:
    diagnostics = [p.to_diagnostic() for p in proposals]
    server.text_document_publish_diagnostics(lsp.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics))


async def emit_event(event) -> Any:
    if not event.timestamp:
        event.timestamp = time.time()
    await server.db.store_event(event)
    if server.event_store:
        core_event = event.to_core_event()
        await server.event_store.append("swarm", core_event)
    server.protocol.notify("$/remora/event", event.model_dump())
    return event


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        text = params.text_document.text

        nodes = server.watcher.parse_and_inject_ids(uri, text)
        await server.db.upsert_nodes(nodes)
        await server.db.update_edges(nodes)

        await refresh_code_lenses()

        proposals = await server.db.get_proposals_for_file(uri)
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

        file_proposals = [p for p in server.proposals.values() if p.file_path == uri]
        await publish_diagnostics(uri, file_proposals)

        for node in nodes:
            tools = await server.discover_tools_for_agent(node)
            node.extra_tools = tools

    except Exception:
        logger.exception("Error in did_open handler")


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri

        if uri in server._injecting:
            server._injecting.discard(uri)
            return

        text = Path(uri_to_path(uri)).read_text()

        old_nodes = await server.db.get_nodes_for_file(uri)
        new_nodes = server.watcher.parse_and_inject_ids(uri, text, old_nodes)

        old_by_key = {(n["name"], n["node_type"]): n for n in old_nodes}
        for node in new_nodes:
            key = (node.name, node.node_type)
            if key in old_by_key:
                node.remora_id = old_by_key[key]["id"]
                del old_by_key[key]

        for orphan_key in old_by_key:
            orphan = old_by_key[orphan_key]
            await server.db.set_status(orphan["id"], "orphaned")

        await server.db.upsert_nodes(new_nodes)
        await server.db.update_edges(new_nodes)

        server.graph.invalidate(uri)

        file_path = Path(uri_to_path(uri))
        if file_path.exists():
            server._injecting.add(uri)
            inject_ids(file_path, new_nodes)

        await refresh_code_lenses()

    except Exception:
        logger.exception("Error in did_save handler")


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
async def did_close(params: lsp.DidCloseTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        to_remove = [pid for pid, p in server.proposals.items() if p.file_path == uri]
        for pid in to_remove:
            del server.proposals[pid]
    except Exception:
        logger.exception("Error in did_close handler")


@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    try:
        uri = params.text_document.uri
        pos = params.position

        node = await server.db.get_node_at_position(uri, pos.line + 1, pos.character)
        if not node:
            return None

        agent = ASTAgentNode(**node)
        events = await server.db.get_recent_events(agent.remora_id, limit=5)

        return agent.to_hover(events)
    except Exception:
        logger.exception("Error in hover handler")
        return None


@server.feature(lsp.TEXT_DOCUMENT_CODE_LENS)
async def code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    try:
        uri = params.text_document.uri
        nodes = await server.db.get_nodes_for_file(uri)

        return [ASTAgentNode(**n).to_code_lens() for n in nodes]
    except Exception:
        logger.exception("Error in code_lens handler")
        return []


@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    try:
        uri = params.text_document.uri
        range_ = params.range

        node = await server.db.get_node_at_position(uri, range_.start.line + 1, range_.start.character)
        if not node:
            return []

        agent = ASTAgentNode(**node)
        actions = agent.to_code_actions()

        if agent.pending_proposal_id:
            proposal = server.proposals.get(agent.pending_proposal_id)
            if proposal:
                actions.extend(proposal.to_code_actions())

        return actions
    except Exception:
        logger.exception("Error in code_action handler")
        return []


@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
    try:
        uri = params.text_document.uri
        nodes = await server.db.get_nodes_for_file(uri)

        symbols = []
        for n in nodes:
            agent = ASTAgentNode(**n)
            symbol_kind = {
                "function": lsp.SymbolKind.Function,
                "class": lsp.SymbolKind.Class,
                "method": lsp.SymbolKind.Method,
                "file": lsp.SymbolKind.File,
            }.get(agent.node_type, lsp.SymbolKind.Variable)

            symbols.append(
                lsp.DocumentSymbol(
                    name=f"{agent.name} [{agent.remora_id}]",
                    kind=symbol_kind,
                    range=agent.to_range(),
                    selection_range=agent.to_range(),
                    detail=f"Status: {agent.status}",
                )
            )

        return symbols
    except Exception:
        logger.exception("Error in document_symbol handler")
        return []


@server.feature(lsp.WORKSPACE_EXECUTE_COMMAND)
async def execute_command(params: lsp.ExecuteCommandParams) -> Any:
    try:
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
                    node = await server.db.get_node(agent_id)
                    if node:
                        agent = ASTAgentNode(**node)
                        await server.runner.execute_extension_tool(
                            agent, tool_name, tool_params, server.generate_correlation_id()
                        )

            case "remora.acceptProposal":
                proposal_id = args[0]
                proposal = server.proposals.get(proposal_id)
                if not proposal:
                    return

                await server.workspace_apply_edit(lsp.ApplyWorkspaceEditParams(edit=proposal.to_workspace_edit()))

                del server.proposals[proposal_id]
                agent = await server.db.get_node(proposal.agent_id)
                if agent:
                    await server.db.set_status(agent["id"], "active")
                    await server.db.clear_pending_proposal(agent["id"])

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

    except Exception:
        logger.exception("Error in execute_command handler")


@server.feature("$/remora/submitInput")
async def on_input_submitted(params: dict) -> None:
    try:
        if "agent_id" in params:
            agent_id = params["agent_id"]
            message = params["input"]

            correlation_id = server.generate_correlation_id()
            await emit_event(HumanChatEvent(to_agent=agent_id, message=message, correlation_id=correlation_id))

            if server.subscriptions and server.event_store:
                from remora.core.events import AgentMessageEvent as CoreMsg

                core_event = CoreMsg(
                    from_agent="human",
                    to_agent=agent_id,
                    content=message,
                )
                await server.event_store.append("swarm", core_event)

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

    except Exception:
        logger.exception("Error in on_input_submitted handler")


async def discover_tools_for_agent(agent: ASTAgentNode) -> list[ToolSchema]:
    """Discover Grail tools from bundle and convert to ToolSchema for LSP code actions."""
    try:
        from remora.core.config import load_config
        from remora.core.tools.grail import discover_grail_tools

        config = load_config()
        bundle_name = config.bundle_mapping.get(agent.node_type)
        if not bundle_name:
            return []

        bundle_dir = Path(config.bundle_root) / bundle_name / "tools"
        if not bundle_dir.exists():
            return []

        grail_tools = discover_grail_tools(str(bundle_dir), {}, lambda: {})
        return [
            ToolSchema(
                name=t.schema.name,
                description=t.schema.description,
                parameters=t.schema.parameters,
            )
            for t in grail_tools
        ]
    except Exception:
        logger.exception("Error discovering tools for agent")
        return []


RemoraLanguageServer.discover_tools_for_agent = discover_tools_for_agent


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()
