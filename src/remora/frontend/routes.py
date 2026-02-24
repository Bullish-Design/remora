from dataclasses import dataclass

from stario import Context, Stario, Writer
from remora.event_bus import EventBus, get_event_bus
from remora.frontend.registry import workspace_registry
from remora.frontend.state import dashboard_state
from remora.frontend.views import dashboard_view
from remora.interactive import WorkspaceInboxCoordinator
from remora.workspace import GraphWorkspace


@dataclass
class RespondSignals:
    agent_id: str = ""
    msg_id: str = ""
    question: str = ""
    answer: str = ""


_coordinator: WorkspaceInboxCoordinator | None = None


def get_coordinator(event_bus: EventBus | None = None) -> WorkspaceInboxCoordinator:
    global _coordinator
    bus = event_bus or get_event_bus()
    if _coordinator is None:
        _coordinator = WorkspaceInboxCoordinator(bus)
    return _coordinator


async def register_agent_workspace(
    agent_id: str,
    workspace: GraphWorkspace,
    workspace_id: str | None = None,
) -> None:
    """Register an agent with a workspace for KV-based communication.

    This must be called when an agent starts, before any blocking occurs.

    Args:
        agent_id: Unique identifier for the agent
        workspace: The GraphWorkspace the agent is using
        workspace_id: Optional workspace ID (defaults to workspace.id)
    """
    ws_id = workspace_id or workspace.id
    await workspace_registry.register(agent_id, ws_id, workspace)
    coordinator = get_coordinator()
    await coordinator.watch_workspace(agent_id, workspace)


async def unregister_agent(agent_id: str) -> None:
    """Unregister an agent and stop watching its workspace.

    Args:
        agent_id: Unique identifier for the agent
    """
    coordinator = get_coordinator()
    await coordinator.stop_watching(agent_id)
    workspace_registry.unregister(agent_id)


def register_routes(app: Stario, event_bus: EventBus | None = None) -> WorkspaceInboxCoordinator:
    bus = event_bus or get_event_bus()
    coordinator = get_coordinator(bus)

    async def home(context: Context, writer: Writer) -> None:
        writer.html(dashboard_view(dashboard_state))

    async def events(context: Context, writer: Writer) -> None:
        async with writer.alive(bus.stream()) as stream:
            async for event in stream:
                dashboard_state.record(event)
                writer.patch(dashboard_view(dashboard_state))
                writer.sync(dashboard_state.get_signals())

    async def respond(context: Context, writer: Writer, agent_id: str) -> None:
        signals = await context.signals(RespondSignals)

        if not signals.agent_id or not signals.answer:
            writer.json({"error": "Missing required fields: agent_id and answer are required"}, status=400)
            return

        msg_id = signals.msg_id
        if not msg_id:
            for blocked in dashboard_state.blocked.values():
                if blocked.get("agent_id") == signals.agent_id:
                    msg_id = blocked.get("msg_id", "")
                    if msg_id:
                        break

        if not msg_id:
            writer.json({"error": "No pending question found for this agent"}, status=400)
            return

        workspace = workspace_registry.get_workspace(signals.agent_id)
        if not workspace:
            writer.json(
                {"error": "No workspace found for agent. Is the agent still running?"},
                status=400,
            )
            return

        try:
            await coordinator.respond(
                agent_id=signals.agent_id,
                msg_id=msg_id,
                answer=signals.answer,
                workspace=workspace,
            )
            writer.json({"status": "ok", "agent_id": signals.agent_id, "msg_id": msg_id})
        except Exception as exc:
            writer.json({"error": f"Failed to send response: {exc}"}, status=500)

    app.get("/", home)
    app.get("/events", events)
    app.post("/agent/{agent_id}/respond", respond)

    return coordinator
