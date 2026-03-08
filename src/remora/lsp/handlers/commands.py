from __future__ import annotations

import asyncio
import logging
import time

from lsprotocol import types as lsp

from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp")

RESOLVE_AGENT_TIMEOUT_SECONDS = 5.0
GET_PANEL_NODE_TIMEOUT_SECONDS = 4.0
GET_PANEL_EVENTS_TIMEOUT_SECONDS = 4.0


async def _resolve_agent(ls: LspServer, args) -> str | None:
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
    if not ls.event_store:
        logger.warning("_resolve_agent: no event_store available")
        return None
    logger.info(
        "_resolve_agent: get_node_at_position START uri=%s line=%s timeout_s=%.2f",
        uri,
        line,
        RESOLVE_AGENT_TIMEOUT_SECONDS,
    )
    start = time.monotonic()
    try:
        agent = await asyncio.wait_for(
            ls.event_store.nodes.get_node_at_position(uri, line),
            timeout=RESOLVE_AGENT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            "_resolve_agent: get_node_at_position TIMEOUT uri=%s line=%s duration_ms=%.1f timeout_s=%.2f",
            uri,
            line,
            duration_ms,
            RESOLVE_AGENT_TIMEOUT_SECONDS,
        )
        raise
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "_resolve_agent: get_node_at_position END uri=%s line=%s duration_ms=%.1f found=%s",
        uri,
        line,
        duration_ms,
        bool(agent),
    )
    if agent:
        logger.info("_resolve_agent: FOUND agent %s (%s) at %s:%s", agent.node_id, agent.name, uri, line)
        return agent.node_id
    logger.warning("_resolve_agent: NO agent found at %s:%s", uri, line)
    return None


async def cmd_get_agent_panel(ls: LspServer, *args) -> dict | None:
    """Return agent info + tools + recent events for the agent at cursor."""
    try:
        logger.info("cmd_get_agent_panel: args=%r", args)
        ctx = args[0] if args else None
        if not ctx or not isinstance(ctx, dict):
            logger.warning("cmd_get_agent_panel: no valid cursor context")
            return None
        uri = ctx.get("uri")
        line = ctx.get("line")
        if not uri or line is None:
            logger.warning("cmd_get_agent_panel: missing uri=%r or line=%r", uri, line)
            return None
        if not ls.event_store:
            return None

        logger.info(
            "cmd_get_agent_panel: get_node_at_position START uri=%s line=%s timeout_s=%.2f",
            uri,
            line,
            GET_PANEL_NODE_TIMEOUT_SECONDS,
        )
        read_start = time.monotonic()
        try:
            agent = await asyncio.wait_for(
                ls.event_store.nodes.get_node_at_position(uri, line),
                timeout=GET_PANEL_NODE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            read_duration_ms = (time.monotonic() - read_start) * 1000
            logger.warning(
                "cmd_get_agent_panel: get_node_at_position TIMEOUT uri=%s line=%s duration_ms=%.1f timeout_s=%.2f",
                uri,
                line,
                read_duration_ms,
                GET_PANEL_NODE_TIMEOUT_SECONDS,
            )
            return {"error": "Timed out resolving agent at cursor"}
        read_duration_ms = (time.monotonic() - read_start) * 1000
        logger.info(
            "cmd_get_agent_panel: get_node_at_position END uri=%s line=%s duration_ms=%.1f found=%s",
            uri,
            line,
            read_duration_ms,
            bool(agent),
        )
        if not agent:
            logger.info("cmd_get_agent_panel: no agent at %s:%s", uri, line)
            return None

        logger.info("cmd_get_agent_panel: found agent %s (%s)", agent.node_id, agent.name)

        # Get tools
        tools = []
        if ls.runner:
            raw_tools = ls.runner.get_agent_tools(agent)
            tools = [
                {"name": t["function"]["name"], "description": t["function"].get("description", "")} for t in raw_tools
            ]

        # Get recent events (newest first from EventStore, reverse for chronological display)
        logger.info(
            "cmd_get_agent_panel: get_recent_events START agent=%s limit=50 timeout_s=%.2f",
            agent.node_id,
            GET_PANEL_EVENTS_TIMEOUT_SECONDS,
        )
        events_start = time.monotonic()
        try:
            events = await asyncio.wait_for(
                ls.event_store.get_recent_events(agent.node_id, limit=50),
                timeout=GET_PANEL_EVENTS_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            events_duration_ms = (time.monotonic() - events_start) * 1000
            logger.warning(
                "cmd_get_agent_panel: get_recent_events TIMEOUT agent=%s duration_ms=%.1f timeout_s=%.2f",
                agent.node_id,
                events_duration_ms,
                GET_PANEL_EVENTS_TIMEOUT_SECONDS,
            )
            return {"error": "Timed out loading panel events"}
        events_duration_ms = (time.monotonic() - events_start) * 1000
        logger.info(
            "cmd_get_agent_panel: get_recent_events END agent=%s duration_ms=%.1f count=%d",
            agent.node_id,
            events_duration_ms,
            len(events),
        )
        event_dicts = list(reversed(events))

        result = {
            "agent": {
                "id": agent.node_id,
                "name": agent.name,
                "node_type": agent.node_type,
                "status": agent.status,
                "start_line": agent.start_line,
                "end_line": agent.end_line,
                "file_path": agent.file_path,
            },
            "tools": tools,
            "events": event_dicts,
        }
        logger.info(
            "cmd_get_agent_panel: returning agent=%s tools=%d events=%d", agent.node_id, len(tools), len(event_dicts)
        )
        return result
    except Exception:
        logger.exception("Error in remora.getAgentPanel")
        return None


async def cmd_chat(ls: LspServer, *args) -> None:
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
    except TimeoutError:
        logger.warning("cmd_chat: agent resolution timed out")
        ls.window_show_message(
            lsp.ShowMessageParams(
                type=lsp.MessageType.Error,
                message="Timed out resolving agent at cursor. Please retry.",
            )
        )
    except Exception:
        logger.exception("Error in remora.chat")


async def cmd_request_rewrite(ls: LspServer, *args) -> None:
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
    except TimeoutError:
        logger.warning("cmd_request_rewrite: agent resolution timed out")
        ls.window_show_message(
            lsp.ShowMessageParams(
                type=lsp.MessageType.Error,
                message="Timed out resolving agent at cursor. Please retry.",
            )
        )
    except Exception:
        logger.exception("Error in remora.requestRewrite")


async def cmd_execute_tool(ls: LspServer, agent_id: str, tool_name: str, *args) -> None:
    try:
        tool_params = args[0] if args else {}
        if ls.runner and ls.event_store:
            agent = await ls.event_store.nodes.get_node(agent_id)
            if agent:
                await ls.runner.execute_extension_tool(agent, tool_name, tool_params, ls.generate_correlation_id())
    except Exception:
        logger.exception("Error in remora.executeTool")


async def cmd_accept_proposal(ls: LspServer, proposal_id: str) -> None:
    try:
        await ls.accept_proposal(proposal_id)
    except Exception:
        logger.exception("Error in remora.acceptProposal")


async def cmd_reject_proposal(ls: LspServer, proposal_id: str) -> None:
    try:
        ls.protocol.notify(
            "$/remora/requestInput",
            {"proposal_id": proposal_id, "prompt": "Feedback for agent:"},
        )
    except Exception:
        logger.exception("Error in remora.rejectProposal")


async def cmd_select_agent(ls: LspServer, agent_id: str) -> None:
    try:
        ls.protocol.notify("$/remora/agentSelected", {"agent_id": agent_id})
    except Exception:
        logger.exception("Error in remora.selectAgent")


async def cmd_message_node(ls: LspServer, agent_id: str) -> None:
    try:
        ls.protocol.notify(
            "$/remora/requestInput",
            {"agent_id": agent_id, "prompt": "Message to send:"},
        )
    except Exception:
        logger.exception("Error in remora.messageNode")


def register_command_handlers(server: LspServer) -> None:
    server.command("remora.getAgentPanel")(cmd_get_agent_panel)
    server.command("remora.chat")(cmd_chat)
    server.command("remora.requestRewrite")(cmd_request_rewrite)
    server.command("remora.executeTool")(cmd_execute_tool)
    server.command("remora.acceptProposal")(cmd_accept_proposal)
    server.command("remora.rejectProposal")(cmd_reject_proposal)
    server.command("remora.selectAgent")(cmd_select_agent)
    server.command("remora.messageNode")(cmd_message_node)
