from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import ASTAgentNode, RewriteProposal
from remora.lsp.server import logger, server


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
