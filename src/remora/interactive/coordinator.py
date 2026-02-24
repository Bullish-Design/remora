"""Workspace-based coordinator for handling interactive agents.

This module watches workspace KV stores for agent questions and writes responses.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from remora.event_bus import Event, EventBus


class QuestionPayload(BaseModel):
    """Payload from agent's outbox question."""

    question: str
    options: list[str] | None = None
    status: str
    created_at: str
    timeout: float
    msg_id: str = ""


class WorkspaceInboxCoordinator:
    """Watches workspace KV stores for agent questions and writes responses.

    This is the "parent process" side of the Workspace KV IPC pattern.
    """

    def __init__(self, event_bus: EventBus, poll_interval: float = 0.5):
        self.event_bus = event_bus
        self._watchers: dict[str, asyncio.Task] = {}
        self._poll_interval = poll_interval
        self._logger = logging.getLogger(__name__)

    async def watch_workspace(self, agent_id: str, workspace: Any) -> None:
        """Start watching a workspace for outbox questions."""

        async def watcher():
            while True:
                try:
                    questions = await self._list_pending_questions(workspace)

                    for q in questions:
                        if q.status == "pending":
                            await self.event_bus.publish(
                                Event.agent_blocked(
                                    agent_id=agent_id, question=q.question, options=q.options or [], msg_id=q.msg_id
                                )
                            )
                except asyncio.CancelledError:
                    break
                except Exception:
                    self._logger.exception(f"Error watching workspace for {agent_id}")

                await asyncio.sleep(self._poll_interval)

        self._watchers[agent_id] = asyncio.create_task(watcher())

    async def respond(self, agent_id: str, msg_id: str, answer: str, workspace: Any) -> None:
        """Write a response to the agent's inbox."""
        inbox_key = f"inbox:response:{msg_id}"

        await workspace.kv.set(
            inbox_key,
            {
                "answer": answer,
                "responded_at": datetime.now().isoformat(),
            },
        )

        await self.event_bus.publish(Event.agent_resumed(agent_id=agent_id, answer=answer, msg_id=msg_id))

    async def stop_watching(self, agent_id: str) -> None:
        """Stop watching a workspace."""
        if agent_id in self._watchers:
            self._watchers[agent_id].cancel()
            try:
                await self._watchers[agent_id]
            except asyncio.CancelledError:
                pass
            del self._watchers[agent_id]

    async def stop_all(self) -> None:
        """Stop all watchers."""
        for agent_id in list(self._watchers.keys()):
            await self.stop_watching(agent_id)

    async def _list_pending_questions(self, workspace: Any) -> list[QuestionPayload]:
        """List all pending questions in the workspace outbox."""
        try:
            entries = await workspace.kv.list(prefix="outbox:question:")
        except Exception:
            return []

        questions = []

        for entry in entries:
            key = entry.get("key", "") if isinstance(entry, dict) else str(entry)
            if not key.startswith("outbox:question:"):
                continue

            try:
                data = await workspace.kv.get(key)
                if data:
                    msg_id = key.split(":")[-1]
                    questions.append(QuestionPayload(**data, msg_id=msg_id))
            except Exception:
                continue

        return questions
