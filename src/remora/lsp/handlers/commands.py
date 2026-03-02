from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import ASTAgentNode, RewriteAppliedEvent, RewriteRejectedEvent
from remora.lsp.server import emit_event, logger, server


async def _resolve_agent(ls, args) -> str | None:
    """Resolve an agent_id from cursor context {uri, line} passed as args[0]."""
    logger.info("_resolve_agent: args=%r", args)
    ctx = args[0] if args else None
    if not ctx or not isinstance(ctx, dict):
        logger.warning("_resolve_agent: no valid cursor context in args")
        return None
    uri = ctx.get("uri")
    line = ctx.get("line")
    if not uri or line is None:
        logger.warning("_resolve_agent: missing uri=%r or line=%r", uri, line)
        return None
    logger.info("_resolve_agent: querying DB for node at %s:%s", uri, line)
    node = await ls.db.get_node_at_position(uri, line, 0)
    if node:
        logger.info("_resolve_agent: FOUND agent %s (%s) at %s:%s", node["remora_id"], node["name"], uri, line)
        return node["remora_id"]
    logger.warning("_resolve_agent: NO agent found at %s:%s", uri, line)
    return None


@server.command("remora.chat")
async def cmd_chat(ls, *args) -> None:
    try:
        logger.info("cmd_chat: called with args=%r", args)
        agent_id = await _resolve_agent(ls, args)
        if not agent_id:
            logger.warning("cmd_chat: no agent resolved — showing warning to user")
            ls.window_show_message(
                lsp.ShowMessageParams(
                    type=lsp.MessageType.Warning,
                    message="No agent found at cursor — open a Python file first",
                )
            )
            return
        logger.info("cmd_chat: sending requestInput for agent=%s", agent_id)
        ls.protocol.notify(
            "$/remora/requestInput",
            {"agent_id": agent_id, "prompt": "Message to agent:"},
        )
        logger.info("cmd_chat: requestInput sent")
    except Exception:
        logger.exception("Error in remora.chat")


@server.command("remora.requestRewrite")
async def cmd_request_rewrite(ls, *args) -> None:
    try:
        agent_id = await _resolve_agent(ls, args)
        if not agent_id:
            ls.window_show_message(
                lsp.ShowMessageParams(
                    type=lsp.MessageType.Warning,
                    message="No agent found at cursor — open a Python file first",
                )
            )
            return
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
