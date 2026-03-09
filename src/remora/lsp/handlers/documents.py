from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from lsprotocol import types as lsp
from pygls.uris import to_fs_path

from remora.core.code.discovery import CSTNode, node_to_event, parse_content
from remora.core.events.code_events import NodeRemovedEvent
from remora.core.events.interaction_events import ContentChangedEvent, FileSavedEvent
from remora.lsp.protocols import LspServer
from remora.runner.models import RewriteProposal

logger = logging.getLogger("remora.lsp")


def _uri_to_path(uri: str) -> str:
    try:
        return to_fs_path(uri)
    except Exception:
        return uri


async def _emit_node_events(ls: LspServer, uri: str, new_nodes: list[CSTNode]) -> None:
    """Emit NodeDiscovered/NodeRemoved events for a file's parse results."""
    if not ls.event_store:
        return

    old_agents = await ls.event_store.nodes.list_nodes(file_path=uri)
    old_ids = {a.node_id for a in old_agents}
    new_ids = {n.node_id for n in new_nodes}

    for orphan_id in old_ids - new_ids:
        await ls.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))

    for node in new_nodes:
        await ls.event_store.append("nodes", node_to_event(node))


async def did_open(ls: LspServer, params: lsp.DidOpenTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        text = params.text_document.text
        logger.info("did_open: uri=%s text_len=%d", uri, len(text))

        new_nodes = parse_content(uri, text)
        logger.info("did_open: parsed %d nodes from %s", len(new_nodes), uri)
        for node in new_nodes:
            logger.debug(
                "did_open:   node: %s (%s) lines %d-%d", node.name, node.node_type, node.start_line, node.end_line
            )

        await _emit_node_events(ls, uri, new_nodes)

        bootstrap_runner = getattr(ls, "bootstrap_runner", None)
        if bootstrap_runner is not None:
            async def _activate_bootstrap_for_file() -> None:
                try:
                    await bootstrap_runner.run_for_file(uri)
                except Exception:
                    logger.exception("did_open: bootstrap file activation failed for %s", uri)

            asyncio.create_task(_activate_bootstrap_for_file())

        # Update edges in RemoraDB (edges stay in RemoraDB for now)
        await ls.db.update_edges(new_nodes)
        logger.debug("did_open: emitted node events + updated edges")

        await ls.refresh_code_lenses()

        proposals = await ls.db.get_proposals_for_file(uri)
        logger.debug("did_open: %d proposals for %s", len(proposals), uri)
        for p in proposals:
            proposal = RewriteProposal(
                proposal_id=p["proposal_id"],
                agent_id=p["agent_id"],
                file_path=p["file_path"],
                old_source=p["old_source"],
                new_source=p["new_source"],
                start_line=1,
                end_line=len(p["new_source"].splitlines()),
                reasoning="",
                correlation_id="",
            )
            ls.proposals[p["proposal_id"]] = proposal

        file_proposals = [p for p in ls.proposals.values() if p.file_path == uri]
        await ls.publish_diagnostics(uri, file_proposals)

        # Discover tools for each agent node from EventStore
        if ls.event_store:
            agents = await ls.event_store.nodes.list_nodes(file_path=uri)
            for agent in agents:
                # Discover tools so they are cached on the server for later use.
                # Tools are not persisted to the node row because they are
                # re-discovered on every file open/save, making persistence
                # redundant for now.
                await ls.discover_tools_for_agent(agent)

        # Notify client of updated agent list
        await ls.notify_agents_updated()
    except Exception:
        logger.exception("Error in did_open handler")


async def did_change(ls: LspServer, params: lsp.DidChangeTextDocumentParams) -> None:
    """Debounced reparse on every edit — updates nodes + code lenses.

    Does NOT emit ContentChangedEvent (that only fires on save).
    Does NOT inject IDs or update edges (those happen on save only).
    """
    try:
        uri = params.text_document.uri
        if not params.content_changes:
            return
        # Full-sync: the last content change contains the full document text
        text = params.content_changes[-1].text
        logger.debug("did_change: scheduling reparse for %s (%d chars)", uri, len(text))
        ls.schedule_reparse(uri, text, delay_ms=500)
    except Exception:
        logger.exception("Error in did_change handler")


async def did_save(ls: LspServer, params: lsp.DidSaveTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        logger.info("did_save: uri=%s", uri)

        # Prefer LSP-provided text to avoid disk read race
        text = params.text if params.text is not None else Path(_uri_to_path(uri)).read_text()
        logger.debug("did_save: read %d chars from %s", len(text), uri)

        new_nodes = parse_content(uri, text)
        logger.info("did_save: parsed %d nodes for %s", len(new_nodes), uri)

        if ls.event_store:
            await _emit_node_events(ls, uri, new_nodes)

            # Emit file-level reactive events (Gap #10 — reactive loop)
            await ls.event_store.append("files", FileSavedEvent(path=uri))
            await ls.event_store.append("files", ContentChangedEvent(path=uri))

        # Update edges in RemoraDB
        await ls.db.update_edges(new_nodes)

        await ls.graph.invalidate(uri)

        await ls.refresh_code_lenses()

        # Notify client of updated agent list
        await ls.notify_agents_updated()
    except Exception:
        logger.exception("Error in did_save handler")


async def did_close(ls: LspServer, params: lsp.DidCloseTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        to_remove = [pid for pid, p in ls.proposals.items() if p.file_path == uri]
        for pid in to_remove:
            del ls.proposals[pid]
    except Exception:
        logger.exception("Error in did_close handler")

def register_document_handlers(server: LspServer) -> None:
    server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)(did_open)
    server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)(did_change)
    server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)(did_save)
    server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)(did_close)
