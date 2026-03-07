from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from remora.core.agents.agent_node import ToolSchema

logger = logging.getLogger("remora.lsp")


async def discover_tools_for_agent(agent: Any) -> list[ToolSchema]:
    """Discover bundle Grail tools for a single agent node."""
    try:
        from remora.core.config import load_config
        from remora.core.tools.grail import discover_grail_tools

        config = load_config()
        bundle_name = config.bundle_mapping.get(agent.node_type)
        if not bundle_name:
            return []

        bundle_dir = Path(config.bundle_root) / bundle_name / "tools"
        if not bundle_dir.exists():
            return []

        grail_tools = discover_grail_tools(str(bundle_dir), {}, lambda: {})
        return [
            ToolSchema(
                name=t.schema.name,
                description=t.schema.description,
                parameters=t.schema.parameters,
            )
            for t in grail_tools
        ]
    except Exception:
        logger.exception("Error discovering tools for agent")
        return []


__all__ = ["discover_tools_for_agent"]
