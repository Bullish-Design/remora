from __future__ import annotations
import logging

from lsprotocol import types as lsp

from remora.runner.models import RewriteProposal
from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp")

async def code_action(ls: LspServer, params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    try:
        uri = params.text_document.uri
        range_ = params.range
        if not ls.event_store:
            return []

        agent = await ls.event_store.nodes.get_node_at_position(uri, range_.start.line + 1)
        if not agent:
            return []

        actions = agent.to_code_actions()

        # Check for pending proposals via RemoraDB proposals table
        proposals_for_agent = [p for p in ls.proposals.values() if p.agent_id == agent.node_id]
        for proposal in proposals_for_agent:
            actions.extend(proposal.to_code_actions())

        return actions
    except Exception:
        logger.exception("Error in code_action handler")
        return []

def register_action_handlers(server: LspServer) -> None:
    server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)(code_action)
