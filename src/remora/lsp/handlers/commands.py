from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import ASTAgentNode, RewriteAppliedEvent, RewriteRejectedEvent
from remora.lsp.server import emit_event, logger, server


@server.command("remora.chat")
async def cmd_chat(ls, *args) -> None:
    try:
        agent_id = args[0] if args else None
        ls.protocol.notify(
            "$/remora/requestInput",
            {"agent_id": agent_id, "prompt": "Message to agent:"},
        )
    except Exception:
        logger.exception("Error in remora.chat")


@server.command("remora.requestRewrite")
async def cmd_request_rewrite(ls, *args) -> None:
    try:
        agent_id = args[0] if args else None
        ls.protocol.notify(
            "$/remora/requestInput",
            {"agent_id": agent_id, "prompt": "What should this code do?"},
        )
    except Exception:
        logger.exception("Error in remora.requestRewrite")


@server.command("remora.executeTool")
async def cmd_execute_tool(ls, agent_id: str, tool_name: str, *args) -> None:
    try:
        tool_params = args[0] if args else {}
        if ls.runner:
            node = await ls.db.get_node(agent_id)
            if node:
                agent = ASTAgentNode(**node)
                await ls.runner.execute_extension_tool(agent, tool_name, tool_params, ls.generate_correlation_id())
    except Exception:
        logger.exception("Error in remora.executeTool")


@server.command("remora.acceptProposal")
async def cmd_accept_proposal(ls, proposal_id: str) -> None:
    try:
        proposal = ls.proposals.get(proposal_id)
        if not proposal:
            return

        await ls.workspace_apply_edit(lsp.ApplyWorkspaceEditParams(edit=proposal.to_workspace_edit()))

        del ls.proposals[proposal_id]
        agent = await ls.db.get_node(proposal.agent_id)
        if agent:
            await ls.db.set_status(agent["id"], "active")
            await ls.db.clear_pending_proposal(agent["id"])

        await emit_event(
            RewriteAppliedEvent(
                agent_id=proposal.agent_id,
                proposal_id=proposal_id,
                correlation_id=proposal.correlation_id or "",
                timestamp=0.0,
            )
        )
    except Exception:
        logger.exception("Error in remora.acceptProposal")


@server.command("remora.rejectProposal")
async def cmd_reject_proposal(ls, proposal_id: str) -> None:
    try:
        ls.protocol.notify(
            "$/remora/requestInput",
            {"proposal_id": proposal_id, "prompt": "Feedback for agent:"},
        )
    except Exception:
        logger.exception("Error in remora.rejectProposal")


@server.command("remora.selectAgent")
async def cmd_select_agent(ls, agent_id: str) -> None:
    try:
        ls.protocol.notify("$/remora/agentSelected", {"agent_id": agent_id})
    except Exception:
        logger.exception("Error in remora.selectAgent")


@server.command("remora.messageNode")
async def cmd_message_node(ls, agent_id: str) -> None:
    try:
        ls.protocol.notify(
            "$/remora/requestInput",
            {"agent_id": agent_id, "prompt": "Message to send:"},
        )
    except Exception:
        logger.exception("Error in remora.messageNode")
