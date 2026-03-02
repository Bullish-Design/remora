from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import RewriteProposal
from remora.lsp.server import logger, server


@server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
async def code_action(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    try:
        uri = params.text_document.uri
        range_ = params.range
        if not server.event_store:
            return []

        agent = await server.event_store.get_node_at_position(uri, range_.start.line + 1)
        if not agent:
            return []

        actions = agent.to_code_actions()

        # Check for pending proposals via RemoraDB proposals table
        proposals_for_agent = [p for p in server.proposals.values() if p.agent_id == agent.node_id]
        for proposal in proposals_for_agent:
            actions.extend(proposal.to_code_actions())

        return actions
    except Exception:
        logger.exception("Error in code_action handler")
        return []
