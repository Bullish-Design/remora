from __future__ import annotations

import asyncio
import logging
import time

from lsprotocol import types as lsp

from remora.core.events.agent_events import HumanChatEvent, HumanInputResponseEvent, RewriteRejectedEvent
from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp")

SUBMIT_EMIT_EVENT_TIMEOUT_SECONDS = 2.0
SUBMIT_RUNNER_TRIGGER_TIMEOUT_SECONDS = 2.0


async def on_cursor_moved(ls: LspServer, params: dict) -> None:
    """Handle cursor position updates from neovim for web graph view.

    Debounced (200ms): the actual DB update and CursorFocusEvent emission
    only fire after the cursor has been stable for 200ms.
    """
    try:
        if not isinstance(params, dict):
            params = {
                "uri": getattr(params, "uri", None),
                "line": getattr(params, "line", None),
            }
        uri = params.get("uri")
        line = params.get("line")
        if not uri or line is None:
            return
        # Resolve which agent (if any) the cursor is on
        node = await ls.event_store.nodes.get_node_at_position(uri, line)
        agent_id = node.node_id if node else None
        # Debounce: actual DB write + CursorFocusEvent emission delayed 200ms
        ls.schedule_cursor_update(agent_id, uri, line, delay_ms=200)
    except Exception:
        logger.debug("Error in on_cursor_moved handler", exc_info=True)

async def on_input_submitted(ls: LspServer, params: dict) -> None:
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
                "request_id": getattr(params, "request_id", None),
                "node_id": getattr(params, "node_id", None),
                "question": getattr(params, "question", None),
            }
            # Drop None entries so "key in params" behaves correctly
            params = {k: v for k, v in params.items() if v is not None}
            logger.debug("on_input_submitted: coerced to dict keys=%s", list(params.keys()))
        if "request_id" in params:
            request_id = str(params["request_id"]).strip()
            response = str(params.get("input", "")).strip()
            agent_id = str(params.get("agent_id", "")).strip()
            node_id = str(params.get("node_id", "")).strip()
            question = str(params.get("question", "")).strip()

            if not request_id or not response:
                logger.warning(
                    "on_input_submitted: request response missing required fields request_id=%r response_len=%d",
                    request_id,
                    len(response),
                )
                return

            bootstrap_runner = getattr(ls, "bootstrap_runner", None)
            if bootstrap_runner and agent_id and node_id:
                handled = await bootstrap_runner.handle_human_input_response(
                    agent_id=agent_id,
                    node_id=node_id,
                    request_id=request_id,
                    response=response,
                    question=question or None,
                )
                if not handled:
                    logger.warning(
                        "on_input_submitted: bootstrap human response failed agent=%s node=%s request_id=%s",
                        agent_id,
                        node_id,
                        request_id,
                    )
                return

            logger.info(
                "on_input_submitted: fallback HumanInputResponseEvent request_id=%s (no bootstrap routing)",
                request_id,
            )
            await ls.emit_event(HumanInputResponseEvent(request_id=request_id, response=response))

        elif "agent_id" in params:
            agent_id = params["agent_id"]
            message = params["input"]
            logger.info("on_input_submitted: chat message to agent=%s message=%r", agent_id, message[:100])
            ls.note_user_activity("chat_submit")

            correlation_id = ls.generate_correlation_id()
            logger.debug("on_input_submitted: correlation_id=%s", correlation_id)
            emit_start = time.monotonic()
            logger.info(
                "on_input_submitted: emit_event START agent=%s corr=%s timeout_s=%.2f",
                agent_id,
                correlation_id,
                SUBMIT_EMIT_EVENT_TIMEOUT_SECONDS,
            )
            try:
                await asyncio.wait_for(
                    ls.emit_event(
                        HumanChatEvent(
                            agent_id=agent_id,
                            to_agent=agent_id,
                            message=message,
                            correlation_id=correlation_id,
                        )
                    ),
                    timeout=SUBMIT_EMIT_EVENT_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                emit_duration_ms = (time.monotonic() - emit_start) * 1000
                logger.error(
                    "on_input_submitted: emit_event TIMEOUT agent=%s corr=%s duration_ms=%.1f timeout_s=%.2f",
                    agent_id,
                    correlation_id,
                    emit_duration_ms,
                    SUBMIT_EMIT_EVENT_TIMEOUT_SECONDS,
                )
                try:
                    ls.window_show_message(
                        lsp.ShowMessageParams(
                            type=lsp.MessageType.Warning,
                            message="Remora is busy processing workspace scan; chat submit timed out. Please retry.",
                        )
                    )
                except Exception:
                    logger.debug("on_input_submitted: failed to show timeout warning", exc_info=True)
                return
            emit_duration_ms = (time.monotonic() - emit_start) * 1000
            logger.info(
                "on_input_submitted: emit_event END agent=%s corr=%s duration_ms=%.1f",
                agent_id,
                correlation_id,
                emit_duration_ms,
            )
            logger.info("on_input_submitted: HumanChatEvent emitted")

            if ls.runner:
                logger.info("on_input_submitted: triggering runner for agent=%s corr=%s", agent_id, correlation_id)
                trigger_start = time.monotonic()
                try:
                    await asyncio.wait_for(
                        ls.runner.trigger(agent_id, correlation_id),
                        timeout=SUBMIT_RUNNER_TRIGGER_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    trigger_duration_ms = (time.monotonic() - trigger_start) * 1000
                    logger.error(
                        "on_input_submitted: runner trigger TIMEOUT agent=%s corr=%s duration_ms=%.1f timeout_s=%.2f",
                        agent_id,
                        correlation_id,
                        trigger_duration_ms,
                        SUBMIT_RUNNER_TRIGGER_TIMEOUT_SECONDS,
                    )
                    try:
                        ls.window_show_message(
                            lsp.ShowMessageParams(
                                type=lsp.MessageType.Warning,
                                message="Remora runner is busy; your chat was queued but response may be delayed.",
                            )
                        )
                    except Exception:
                        logger.debug("on_input_submitted: failed to show runner timeout warning", exc_info=True)
                    return
                logger.info("on_input_submitted: runner triggered successfully")
            else:
                logger.error("on_input_submitted: NO RUNNER on server!")

        elif "proposal_id" in params:
            proposal_id = params["proposal_id"]
            feedback = params["input"]
            proposal = ls.proposals.get(proposal_id)
            logger.info("on_input_submitted: rejection feedback for proposal=%s", proposal_id)

            if proposal:
                await ls.emit_event(
                    RewriteRejectedEvent(
                        agent_id=proposal.agent_id,
                        proposal_id=proposal_id,
                        feedback=feedback,
                        correlation_id=proposal.correlation_id or "",
                    )
                )

                if ls.runner:
                    await ls.runner.trigger(
                        proposal.agent_id, proposal.correlation_id, context={"rejection_feedback": feedback}
                    )
        else:
            logger.warning("on_input_submitted: unrecognized params — no agent_id or proposal_id")

    except Exception:
        logger.exception("Error in on_input_submitted handler")

def register_notification_handlers(server: LspServer) -> None:
    server.feature("$/remora/cursorMoved")(on_cursor_moved)
    server.feature("$/remora/submitInput")(on_input_submitted)
