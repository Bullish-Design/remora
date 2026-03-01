from __future__ import annotations

from lsprotocol import types as lsp

from remora.lsp.models import ASTAgentNode, RewriteAppliedEvent, RewriteRejectedEvent
from remora.lsp.server import emit_event, logger, server


@server.feature(lsp.WORKSPACE_EXECUTE_COMMAND)
async def execute_command(params: lsp.ExecuteCommandParams) -> None:
    try:
        cmd = params.command
        args = params.arguments or []

        match cmd:
            case "remora.chat":
                agent_id = args[0]
                server.send_notification("$/remora/requestInput", {"agent_id": agent_id, "prompt": "Message to agent:"})

            case "remora.requestRewrite":
                agent_id = args[0]
                server.send_notification(
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
                        timestamp=0.0,
                    )
                )

            case "remora.rejectProposal":
                proposal_id = args[0]
                server.send_notification(
                    "$/remora/requestInput", {"proposal_id": proposal_id, "prompt": "Feedback for agent:"}
                )

            case "remora.selectAgent":
                agent_id = args[0]
                server.send_notification("$/remora/agentSelected", {"agent_id": agent_id})

            case _:
                pass

    except Exception:
        logger.exception("Error in execute_command handler")
