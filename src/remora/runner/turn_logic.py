"""Runner-local helpers that encapsulate core-domain dependencies."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from remora.core.agents.execution import execute_agent_turn
from remora.core.events.agent_events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent
from remora.core.events.code_events import ScaffoldRequestEvent
from remora.extensions import extension_matches, load_extensions

logger = logging.getLogger(__name__)


def load_runner_config() -> Any:
    from remora.core.config import load_config

    return load_config()


async def create_workspace_service(config: Any, project_root: Path) -> Any:
    from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode

    service = CairnWorkspaceService(
        config=config,
        swarm_root=config.swarm_root,
        project_root=project_root,
    )

    init_start = time.monotonic()
    await service.initialize(sync_mode=SyncMode.NONE)
    logger.info(
        "AgentRunner: workspace service initialized mode=none root=%s duration_ms=%.1f",
        project_root,
        (time.monotonic() - init_start) * 1000,
    )
    return service


def apply_agent_extensions(agent: Any) -> Any:
    extensions = load_extensions(Path(".remora/models"))

    for ext_cls in extensions:
        if extension_matches(
            ext_cls,
            agent.node_type,
            agent.name,
            file_path=agent.file_path,
            source_code=agent.source_code,
        ):
            data = ext_cls.get_extension_data()
            for key, value in data.items():
                if hasattr(agent, key):
                    setattr(agent, key, value)
            break

    return agent


async def append_agent_start(event_store: Any, *, agent_id: str, node_name: str) -> None:
    await event_store.append(
        "swarm",
        AgentStartEvent(
            graph_id="swarm",
            agent_id=agent_id,
            node_name=node_name,
        ),
    )


async def append_agent_complete(
    event_store: Any,
    *,
    agent_id: str,
    result_summary: str,
    trigger_event: Any,
) -> None:
    tags = ("scaffold",) if isinstance(trigger_event, ScaffoldRequestEvent) else ()
    await event_store.append(
        "swarm",
        AgentCompleteEvent(
            graph_id="swarm",
            agent_id=agent_id,
            result_summary=result_summary,
            tags=tags,
        ),
    )


async def append_agent_error(event_store: Any, *, agent_id: str, error: str) -> None:
    await event_store.append(
        "swarm",
        AgentErrorEvent(
            graph_id="swarm",
            agent_id=agent_id,
            error=error,
        ),
    )


__all__ = [
    "execute_agent_turn",
    "load_runner_config",
    "create_workspace_service",
    "apply_agent_extensions",
    "append_agent_start",
    "append_agent_complete",
    "append_agent_error",
]
