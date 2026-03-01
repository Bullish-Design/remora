from __future__ import annotations

from remora.lsp.models import AgentMessageEvent, HumanChatEvent, RewriteRejectedEvent
from remora.lsp.server import emit_event, logger, server


@server.feature("$/remora/submitInput")
async def on_input_submitted(params: dict) -> None:
    try:
        if "agent_id" in params:
            agent_id = params["agent_id"]
            message = params["input"]

            correlation_id = server.generate_correlation_id()
            await emit_event(HumanChatEvent(to_agent=agent_id, message=message, correlation_id=correlation_id))

            if server.runner:
                await server.runner.trigger(agent_id, correlation_id)

        elif "proposal_id" in params:
            proposal_id = params["proposal_id"]
            feedback = params["input"]
            proposal = server.proposals.get(proposal_id)

            if proposal:
                await emit_event(
                    RewriteRejectedEvent(
                        agent_id=proposal.agent_id,
                        proposal_id=proposal_id,
                        feedback=feedback,
                        correlation_id=proposal.correlation_id or "",
                        timestamp=0.0,
                    )
                )

                if server.runner:
                    await server.runner.trigger(
                        proposal.agent_id, proposal.correlation_id, context={"rejection_feedback": feedback}
                    )

    except Exception:
        logger.exception("Error in on_input_submitted handler")
