"""LinkerSwarm - discovers cross-node links from exchange text."""
from __future__ import annotations

import time

from remora.companion.events import NodeAgentLinkDiscovered
from remora.companion.node_workspace import LINKS, read_json, write_json
from remora.companion.swarms.base import SwarmContext


class LinkerSwarm:
    """Find node references in the exchange and write them to links.json."""

    async def run(self, ctx: SwarmContext) -> None:
        exchange_text = ctx.user_message + "\n" + ctx.assistant_message
        raw = await read_json(ctx.workspace, LINKS) or []
        existing_targets = {(entry.get("target_node_id"), entry.get("relationship")) for entry in raw}

        new_links: list[dict[str, object]] = []
        test_node_pattern = f"test_{ctx.node.name}"
        if test_node_pattern.lower() in exchange_text.lower():
            key = (test_node_pattern, "tested_by")
            if key not in existing_targets:
                new_links.append(
                    {
                        "target_node_id": test_node_pattern,
                        "relationship": "tested_by",
                        "confidence": 0.6,
                        "note": "Mentioned in exchange",
                        "timestamp": time.time(),
                    }
                )

        if not new_links:
            return

        raw.extend(new_links)
        await write_json(ctx.workspace, LINKS, raw)

        for link in new_links:
            await ctx.event_bus.emit(
                NodeAgentLinkDiscovered(
                    source_node_id=ctx.node_id,
                    target_node_id=str(link["target_node_id"]),
                    relationship=str(link["relationship"]),
                    confidence=float(link["confidence"]),
                    note=str(link.get("note", "")),
                )
            )
