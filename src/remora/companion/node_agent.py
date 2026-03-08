"""NodeAgent - a persistent, per-CST-node agent backed by a Cairn workspace."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel

from remora.companion.events import NodeAgentSidebarReady
from remora.companion.node_workspace import AGENT_NOTES, SOURCE_SNAPSHOT, append_text, ensure_meta, read_text
from remora.companion.sidebar.composer import compose_sidebar
from remora.companion.swarms.base import SwarmContext, run_post_exchange_swarms
from remora.companion.swarms.categorizer import CategorizerSwarm
from remora.companion.swarms.linker import LinkerSwarm
from remora.companion.swarms.reflection import ReflectionSwarm
from remora.companion.swarms.summarizer import SummarizerSwarm
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

if TYPE_CHECKING:
    from remora.companion.config import CompanionConfig
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace
    from remora.core.events.event_bus import EventBus

logger = logging.getLogger("remora.companion.node_agent")

_SWARMS = [SummarizerSwarm(), CategorizerSwarm(), LinkerSwarm(), ReflectionSwarm()]


class NodeMessage(BaseModel):
    """A single message in a node agent conversation."""

    role: str
    content: str
    timestamp: float = 0.0

    @classmethod
    def user(cls, content: str) -> "NodeMessage":
        return cls(role="user", content=content, timestamp=time.time())

    @classmethod
    def assistant(cls, content: str) -> "NodeMessage":
        return cls(role="assistant", content=content, timestamp=time.time())


class NodeAgentResponse(BaseModel):
    """Response from a NodeAgent.send() call."""

    message: NodeMessage
    turn_count: int
    node_id: str


class NodeAgent:
    """Persistent agent for a single CST node."""

    def __init__(
        self,
        node: "AgentNode",
        workspace: "AgentWorkspace",
        event_bus: "EventBus",
        config: "CompanionConfig",
    ) -> None:
        self.node = node
        self.workspace = workspace
        self._event_bus = event_bus
        self._config = config
        self._history: list[NodeMessage] = []
        self._last_visited: float = time.time()
        self._session_id = str(uuid.uuid4())

    @property
    def node_id(self) -> str:
        return self.node.node_id

    async def initialize(self) -> None:
        await ensure_meta(
            self.workspace,
            node_id=self.node.node_id,
            node_type=self.node.node_type,
            name=self.node.name,
            file_path=self.node.file_path,
        )

    async def on_cursor_focus(self) -> None:
        self._last_visited = time.time()
        sidebar = await compose_sidebar(self.node, self.workspace)
        await self._event_bus.emit(NodeAgentSidebarReady(node_id=self.node_id, markdown=sidebar))

    async def on_content_changed(self, path: str, diff: str | None) -> None:
        if diff:
            note = f"\n- *File changed ({time.strftime('%Y-%m-%d')})*: {diff[:120]}\n"
            await append_text(self.workspace, AGENT_NOTES, note)

    async def on_file_saved(self, path: str) -> None:
        try:
            import pathlib

            source = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
            await self.workspace.write(SOURCE_SNAPSHOT, f"```\n{source}\n```")
        except Exception:
            pass
        await self.on_cursor_focus()

    async def on_inter_agent_message(self, from_node_id: str, content: str) -> None:
        ts = int(time.time())
        await self.workspace.write(
            f"inbox/{from_node_id}_{ts}.md",
            f"# Message from `{from_node_id}`\n\n*{time.strftime('%Y-%m-%d %H:%M')}*\n\n{content}\n",
        )
        await self.on_cursor_focus()

    async def send(self, content: str) -> NodeAgentResponse:
        user_msg = NodeMessage.user(content)
        self._history.append(user_msg)

        system_prompt = await self._build_system_prompt()
        kernel_messages = [KernelMessage(role="system", content=system_prompt)]
        kernel_messages += [KernelMessage(role=msg.role, content=msg.content) for msg in self._history]

        tools = self._build_tools()
        kernel = create_kernel(
            model_name=self._config.model_name,
            base_url=self._config.model_base_url,
            api_key=self._config.model_api_key or "EMPTY",
            tools=tools,
            observer=self._event_bus,
        )
        try:
            result = await kernel.run(
                kernel_messages,
                [tool.schema for tool in tools],
                max_turns=self._config.max_turns_per_message,
            )
        finally:
            await kernel.close()

        assistant_msg = NodeMessage.assistant(result.final_message.content or "")
        self._history.append(assistant_msg)
        await self._persist_exchange(user_msg, assistant_msg)

        ctx = SwarmContext(
            node_id=self.node_id,
            node=self.node,
            workspace=self.workspace,
            session_id=self._session_id,
            user_message=content,
            assistant_message=assistant_msg.content,
            event_bus=self._event_bus,
            model_name=self._config.model_name,
            model_base_url=self._config.model_base_url,
            model_api_key=self._config.model_api_key,
        )
        asyncio.create_task(self._run_swarms(ctx))

        return NodeAgentResponse(message=assistant_msg, turn_count=result.turn_count, node_id=self.node_id)

    async def _build_system_prompt(self) -> str:
        base = self.node.to_system_prompt()
        agent_notes = await read_text(self.workspace, AGENT_NOTES)
        if agent_notes.strip():
            base += f"\n# My Observations About This Node\n{agent_notes.strip()}\n"

        from remora.companion.node_workspace import load_chat_index

        index = await load_chat_index(self.workspace)
        if index:
            recent = sorted(index, key=lambda entry: entry.timestamp, reverse=True)[:3]
            summary_block = "\n".join(f"- {entry.summary}" for entry in recent)
            base += f"\n# Recent Conversation History (summaries)\n{summary_block}\n"
        return base

    def _build_tools(self) -> list:
        from remora.companion.node_agent_tools import build_node_agent_tools

        return build_node_agent_tools(self)

    async def _persist_exchange(self, user_msg: NodeMessage, assistant_msg: NodeMessage) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n---\n\n**{timestamp}**\n\n"
            f"**User:** {user_msg.content}\n\n"
            f"**Agent:** {assistant_msg.content}\n"
        )
        await append_text(self.workspace, f"chat/{self._session_id}.md", entry)

    async def _run_swarms(self, ctx: SwarmContext) -> None:
        await run_post_exchange_swarms(ctx, _SWARMS)
        sidebar = await compose_sidebar(self.node, self.workspace)
        await self._event_bus.emit(NodeAgentSidebarReady(node_id=self.node_id, markdown=sidebar))


__all__ = ["NodeAgent", "NodeMessage", "NodeAgentResponse"]
