from __future__ import annotations

from pathlib import Path

from lsprotocol import types as lsp

from remora.core.events import ContentChangedEvent, FileSavedEvent, NodeDiscoveredEvent, NodeRemovedEvent
from remora.lsp.models import RewriteProposal
from remora.lsp.server import logger, publish_diagnostics, refresh_code_lenses, server, uri_to_path
from remora.lsp.watcher import inject_ids


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        text = params.text_document.text
        logger.info("did_open: uri=%s text_len=%d", uri, len(text))

        # Get existing nodes from EventStore as dicts for watcher
        old_agents = await server.event_store.list_nodes(file_path=uri) if server.event_store else []
        old_dicts = [{"name": a.name, "node_type": a.node_type, "node_id": a.node_id} for a in old_agents]

        new_dicts = server.watcher.parse_and_inject_ids(uri, text, old_dicts)
        logger.info("did_open: parsed %d nodes from %s (%d old)", len(new_dicts), uri, len(old_dicts))
        for nd in new_dicts:
            logger.debug(
                "did_open:   node: %s (%s) lines %d-%d", nd["name"], nd["node_type"], nd["start_line"], nd["end_line"]
            )

        # Emit NodeDiscoveredEvent for each node → EventStore projection handles upsert
        if server.event_store:
            for nd in new_dicts:
                event = NodeDiscoveredEvent(
                    node_id=nd["node_id"],
                    node_type=nd["node_type"],
                    name=nd["name"],
                    full_name=nd["full_name"],
                    file_path=nd["file_path"],
                    start_line=nd["start_line"],
                    end_line=nd["end_line"],
                    source_code=nd["source_code"],
                    source_hash=nd["source_hash"],
                    parent_id=nd["parent_id"],
                    start_byte=nd.get("start_byte", 0),
                    end_byte=nd.get("end_byte", 0),
                )
                await server.event_store.append("nodes", event)

        # Update edges in RemoraDB (edges stay in RemoraDB for now)
        await server.db.update_edges(new_dicts)
        logger.debug("did_open: emitted node events + updated edges")

        await refresh_code_lenses()

        proposals = await server.db.get_proposals_for_file(uri)
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
            server.proposals[p["proposal_id"]] = proposal

        file_proposals = [p for p in server.proposals.values() if p.file_path == uri]
        await publish_diagnostics(uri, file_proposals)

        # Discover tools for each agent node from EventStore
        if server.event_store:
            agents = await server.event_store.list_nodes(file_path=uri)
            for agent in agents:
                # Discover tools so they are cached on the server for later use.
                # Tools are not persisted to the node row because they are
                # re-discovered on every file open/save, making persistence
                # redundant for now.
                await server.discover_tools_for_agent(agent)

        # Notify client of updated agent list
        await server.notify_agents_updated()
    except Exception:
        logger.exception("Error in did_open handler")


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
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
        server.schedule_reparse(uri, text, delay_ms=500)
    except Exception:
        logger.exception("Error in did_change handler")


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        logger.info("did_save: uri=%s", uri)

        if uri in server._injecting:
            server._injecting.discard(uri)
            logger.debug("did_save: skipping %s (was injecting)", uri)
            return

        # Prefer LSP-provided text to avoid disk read race
        text = params.text if params.text is not None else Path(uri_to_path(uri)).read_text()
        logger.debug("did_save: read %d chars from %s", len(text), uri)

        # Get existing nodes from EventStore
        old_agents = await server.event_store.list_nodes(file_path=uri) if server.event_store else []
        old_dicts = [{"name": a.name, "node_type": a.node_type, "node_id": a.node_id} for a in old_agents]

        new_dicts = server.watcher.parse_and_inject_ids(uri, text, old_dicts)
        logger.info("did_save: %d old nodes, %d new nodes for %s", len(old_dicts), len(new_dicts), uri)

        # Detect orphans: old node IDs not present in new parse
        new_ids = {nd["node_id"] for nd in new_dicts}
        old_ids = {a.node_id for a in old_agents}

        if server.event_store:
            # Emit NodeRemovedEvent for orphaned nodes
            for orphan_id in old_ids - new_ids:
                logger.debug("did_save: removing orphan %s", orphan_id)
                event = NodeRemovedEvent(node_id=orphan_id)
                await server.event_store.append("nodes", event)

            # Emit NodeDiscoveredEvent for each new/updated node
            for nd in new_dicts:
                event = NodeDiscoveredEvent(
                    node_id=nd["node_id"],
                    node_type=nd["node_type"],
                    name=nd["name"],
                    full_name=nd["full_name"],
                    file_path=nd["file_path"],
                    start_line=nd["start_line"],
                    end_line=nd["end_line"],
                    source_code=nd["source_code"],
                    source_hash=nd["source_hash"],
                    parent_id=nd["parent_id"],
                    start_byte=nd.get("start_byte", 0),
                    end_byte=nd.get("end_byte", 0),
                )
                await server.event_store.append("nodes", event)

            # Emit file-level reactive events (Gap #10 — reactive loop)
            await server.event_store.append("files", FileSavedEvent(path=uri))
            await server.event_store.append("files", ContentChangedEvent(path=uri))

        # Update edges in RemoraDB
        await server.db.update_edges(new_dicts)

        server.graph.invalidate(uri)

        file_path = Path(uri_to_path(uri))
        if file_path.exists() and file_path.suffix == ".py":
            server._injecting.add(uri)
            inject_ids(file_path, new_dicts)

        await refresh_code_lenses()

        # Notify client of updated agent list
        await server.notify_agents_updated()
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
