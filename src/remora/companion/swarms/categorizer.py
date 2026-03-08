"""CategorizerSwarm - tags chat exchanges."""
from __future__ import annotations

import json

from remora.companion.node_workspace import load_chat_index, save_chat_index
from remora.companion.swarms.base import SwarmContext
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

VALID_TAGS = [
    "bug",
    "question",
    "refactor",
    "explanation",
    "debugging",
    "test",
    "documentation",
    "performance",
    "design",
    "tooling",
    "edge_case",
    "insight",
    "todo",
    "warning",
]

CATEGORIZER_SYSTEM = f"""You categorize a chat exchange between a developer and a code agent.
Output a JSON array of 1-3 tags from this list:
{json.dumps(VALID_TAGS)}
Output ONLY the JSON array, nothing else. Example: ["bug", "debugging"]"""


class CategorizerSwarm:
    async def run(self, ctx: SwarmContext) -> None:
        exchange_text = f"User: {ctx.user_message}\n\nAgent: {ctx.assistant_message}"
        kernel = create_kernel(
            model_name=ctx.model_name,
            base_url=ctx.model_base_url,
            api_key=ctx.model_api_key or "EMPTY",
        )
        try:
            messages = [
                KernelMessage(role="system", content=CATEGORIZER_SYSTEM),
                KernelMessage(role="user", content=exchange_text),
            ]
            result = await kernel.run(messages, [], max_turns=1)
            raw = (result.final_message.content or "").strip()
            tags = json.loads(raw)
            if not isinstance(tags, list):
                tags = []
            tags = [tag for tag in tags if tag in VALID_TAGS][:3]
        except Exception:
            tags = []
        finally:
            await kernel.close()

        if not tags:
            return

        index = await load_chat_index(ctx.workspace)
        for entry in reversed(index):
            if entry.session_id == ctx.session_id:
                entry.tags = list(set(entry.tags + tags))
                break
        await save_chat_index(ctx.workspace, index)
