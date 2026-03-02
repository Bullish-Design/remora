from __future__ import annotations

from pathlib import Path

from lsprotocol import types as lsp

from remora.lsp.models import RewriteProposal
from remora.lsp.server import logger, publish_diagnostics, refresh_code_lenses, server, uri_to_path
from remora.lsp.watcher import inject_ids


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
async def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        text = params.text_document.text
        logger.info("did_open: uri=%s text_len=%d", uri, len(text))

        nodes = server.watcher.parse_and_inject_ids(uri, text)
        logger.info("did_open: parsed %d nodes from %s", len(nodes), uri)
        for nd in nodes:
            logger.debug("did_open:   node: %s (%s) lines %d-%d", nd.name, nd.node_type, nd.start_line, nd.end_line)

        await server.db.upsert_nodes(nodes)
        await server.db.update_edges(nodes)
        logger.debug("did_open: upserted nodes + edges")

        await refresh_code_lenses()

        proposals = await server.db.get_proposals_for_file(uri)
        logger.debug("did_open: %d proposals for %s", len(proposals), uri)
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

        # Notify client of updated agent list
        if hasattr(server, "_notify_agents_updated"):
            logger.info("did_open: calling _notify_agents_updated")
            await server._notify_agents_updated()
        else:
            logger.warning("did_open: server has no _notify_agents_updated attribute!")
    except Exception:
        logger.exception("Error in did_open handler")


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
async def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
    try:
        uri = params.text_document.uri
        logger.info("did_save: uri=%s", uri)

        if uri in server._injecting:
            server._injecting.discard(uri)
            logger.debug("did_save: skipping %s (was injecting)", uri)
            return

        text = Path(uri_to_path(uri)).read_text()
        logger.debug("did_save: read %d chars from %s", len(text), uri)

        old_nodes = await server.db.get_nodes_for_file(uri)
        new_nodes = server.watcher.parse_and_inject_ids(uri, text, old_nodes)
        logger.info("did_save: %d old nodes, %d new nodes for %s", len(old_nodes), len(new_nodes), uri)

        old_by_key = {(n["name"], n["node_type"]): n for n in old_nodes}
        for node in new_nodes:
            key = (node.name, node.node_type)
            if key in old_by_key:
                node.remora_id = old_by_key[key]["id"]
                del old_by_key[key]

        for orphan in old_by_key.values():
            logger.debug("did_save: orphaning %s", orphan["id"])
            await server.db.set_status(orphan["id"], "orphaned")

        await server.db.upsert_nodes(new_nodes)
        await server.db.update_edges(new_nodes)

        server.graph.invalidate(uri)

        file_path = Path(uri_to_path(uri))
        if file_path.exists():
            server._injecting.add(uri)
            inject_ids(file_path, new_nodes)

        await refresh_code_lenses()

        # Notify client of updated agent list
        if hasattr(server, "_notify_agents_updated"):
            logger.info("did_save: calling _notify_agents_updated")
            await server._notify_agents_updated()
        else:
            logger.warning("did_save: server has no _notify_agents_updated attribute!")
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
