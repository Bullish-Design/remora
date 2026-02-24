from dataclasses import dataclass

from stario import Context, Writer
from remora.event_bus import Event, get_event_bus
from remora.interactive.coordinator import WorkspaceInboxCoordinator

from . import dashboard_state
from .workspace_registry import workspace_registry
from .views import dashboard_view


@dataclass
class RespondSignals:
    agent_id: str = ""
    msg_id: str = ""
    question: str = ""
    answer: str = ""


_coordinator: WorkspaceInboxCoordinator | None = None


def get_coordinator() -> WorkspaceInboxCoordinator:
    global _coordinator
    if _coordinator is None:
        event_bus = get_event_bus()
        _coordinator = WorkspaceInboxCoordinator(event_bus)
    return _coordinator


async def home(c: Context, w: Writer) -> None:
    w.html(dashboard_view(dashboard_state))


async def events(c: Context, w: Writer) -> None:
    event_bus = get_event_bus()

    async with w.alive(event_bus.stream()) as stream:
        async for event in stream:
            dashboard_state.record(event)
            w.patch(dashboard_view(dashboard_state))
            w.sync(dashboard_state.get_signals())


async def respond(c: Context, w: Writer, agent_id: str) -> None:
    signals = await c.signals(RespondSignals)

    if not signals.agent_id or not signals.answer:
        w.json({"error": "Missing required fields: agent_id and answer are required"}, status=400)
        return

    msg_id = signals.msg_id
    if not msg_id:
        for blocked in dashboard_state.blocked.values():
            if blocked.get("agent_id") == signals.agent_id:
                msg_id = blocked.get("msg_id", "")
                if msg_id:
                    break

    if not msg_id:
        w.json({"error": "No pending question found for this agent"}, status=400)
        return

    workspace = workspace_registry.get_workspace(signals.agent_id)
    if not workspace:
        w.json({"error": "No workspace found for agent. Is the agent still running?"}, status=400)
        return

    coordinator = get_coordinator()
    try:
        await coordinator.respond(
            agent_id=signals.agent_id,
            msg_id=msg_id,
            answer=signals.answer,
            workspace=workspace,
        )
        w.json({"status": "ok", "agent_id": signals.agent_id, "msg_id": msg_id})
    except Exception as e:
        w.json({"error": f"Failed to send response: {str(e)}"}, status=500)
