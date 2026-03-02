from __future__ import annotations

from remora.lsp.models import AgentMessageEvent, HumanChatEvent, RewriteRejectedEvent
from remora.lsp.server import emit_event, logger, server


@server.feature("$/remora/submitInput")
async def on_input_submitted(params: dict) -> None:
    try:
        logger.info("on_input_submitted: params=%r (type=%s)", params, type(params).__name__)
        # pygls may deliver params as an attrs Object (uses __slots__, no __dict__).
        # Normalise to dict so key-based lookups work reliably.
        if not isinstance(params, dict):
            # attrs objects support iteration via attrs.fields or we can
            # just pull known keys via getattr.
            params = {
                "agent_id": getattr(params, "agent_id", None),
                "input": getattr(params, "input", None),
                "proposal_id": getattr(params, "proposal_id", None),
            }
            # Drop None entries so "key in params" behaves correctly
            params = {k: v for k, v in params.items() if v is not None}
            logger.debug("on_input_submitted: coerced to dict keys=%s", list(params.keys()))
        if "agent_id" in params:
            agent_id = params["agent_id"]
            message = params["input"]
            logger.info("on_input_submitted: chat message to agent=%s message=%r", agent_id, message[:100])

            correlation_id = server.generate_correlation_id()
            logger.debug("on_input_submitted: correlation_id=%s", correlation_id)
            await emit_event(
                HumanChatEvent(to_agent=agent_id, message=message, correlation_id=correlation_id, timestamp=0.0)
            )
            logger.info("on_input_submitted: HumanChatEvent emitted")

            if server.runner:
                logger.info("on_input_submitted: triggering runner for agent=%s corr=%s", agent_id, correlation_id)
                await server.runner.trigger(agent_id, correlation_id)
                logger.info("on_input_submitted: runner triggered successfully")
            else:
                logger.error("on_input_submitted: NO RUNNER on server!")

        elif "proposal_id" in params:
            proposal_id = params["proposal_id"]
            feedback = params["input"]
            proposal = server.proposals.get(proposal_id)
            logger.info("on_input_submitted: rejection feedback for proposal=%s", proposal_id)

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
        else:
            logger.warning("on_input_submitted: unrecognized params — no agent_id or proposal_id")

    except Exception:
        logger.exception("Error in on_input_submitted handler")
