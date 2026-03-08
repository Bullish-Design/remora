"""SummarizerSwarm - indexes chat exchanges with a summary."""
from __future__ import annotations

import time

from remora.companion.events import NodeAgentExchangeIndexed
from remora.companion.node_workspace import ChatIndexEntry, load_chat_index, save_chat_index
from remora.companion.swarms.base import SwarmContext
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

SUMMARY_SYSTEM = """You summarize a chat exchange between a developer and a code node agent.
Output a single sentence (max 120 chars) describing what was discussed or accomplished.
Output ONLY the sentence, no preamble."""


class SummarizerSwarm:
    async def run(self, ctx: SwarmContext) -> None:
        exchange_text = f"User: {ctx.user_message}\n\nAgent: {ctx.assistant_message}"
        kernel = create_kernel(
            model_name=ctx.model_name,
            base_url=ctx.model_base_url,
            api_key=ctx.model_api_key or "EMPTY",
        )
        try:
            messages = [
                KernelMessage(role="system", content=SUMMARY_SYSTEM),
                KernelMessage(role="user", content=exchange_text),
            ]
            result = await kernel.run(messages, [], max_turns=1)
            summary = (result.final_message.content or "").strip()[:120]
        finally:
            await kernel.close()

        if not summary:
            summary = ctx.user_message[:80]

        index = await load_chat_index(ctx.workspace)
        index.append(
            ChatIndexEntry(
                session_id=ctx.session_id,
                timestamp=time.time(),
                summary=summary,
                turn_count=1,
            )
        )
        await save_chat_index(ctx.workspace, index)

        await ctx.event_bus.emit(
            NodeAgentExchangeIndexed(
                node_id=ctx.node_id,
                session_id=ctx.session_id,
                summary=summary,
            )
        )
