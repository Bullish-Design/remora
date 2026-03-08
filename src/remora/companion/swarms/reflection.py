"""ReflectionSwarm - distills agent observations into notes/agent_notes.md."""
from __future__ import annotations

import time

from remora.companion.events import NodeAgentNoteUpdated
from remora.companion.node_workspace import AGENT_NOTES, append_text, read_text
from remora.companion.swarms.base import SwarmContext
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

REFLECTION_SYSTEM = """You are observing a conversation between a developer and a code agent.
Extract ONE concrete insight, concern, or recommendation revealed by this exchange.
The insight should be useful to remember for future conversations about this code node.
Write it as a single bullet point starting with "- ".
If there is nothing noteworthy, output exactly: SKIP"""


class ReflectionSwarm:
    async def run(self, ctx: SwarmContext) -> None:
        if len(ctx.user_message) + len(ctx.assistant_message) < 100:
            return

        exchange_text = f"User: {ctx.user_message}\n\nAgent: {ctx.assistant_message}"
        await read_text(ctx.workspace, AGENT_NOTES)

        kernel = create_kernel(
            model_name=ctx.model_name,
            base_url=ctx.model_base_url,
            api_key=ctx.model_api_key or "EMPTY",
        )
        try:
            messages = [
                KernelMessage(role="system", content=REFLECTION_SYSTEM),
                KernelMessage(role="user", content=exchange_text),
            ]
            result = await kernel.run(messages, [], max_turns=1)
            observation = (result.final_message.content or "").strip()
        finally:
            await kernel.close()

        if not observation or observation == "SKIP" or not observation.startswith("- "):
            return

        timestamp = time.strftime("%Y-%m-%d")
        note_line = f"\n{observation} *(from {timestamp})*\n"
        await append_text(ctx.workspace, AGENT_NOTES, note_line)
        await ctx.event_bus.emit(NodeAgentNoteUpdated(node_id=ctx.node_id, note_type="agent_notes"))
