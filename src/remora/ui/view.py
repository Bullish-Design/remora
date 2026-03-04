"""UI rendering helpers for the Datastar HTML view."""

from __future__ import annotations

from typing import Any

from remora.ui.components import (
    AgentStatusList,
    Card,
    EventsList,
    GraphLauncher,
    ProgressBar,
    ResultsList,
)
from remora.ui.components.base import Element, RawHTML


def render_blocked_list(blocked: list[dict[str, Any]]) -> str:
    """Render the blocked agents list."""
    from remora.ui.components.dashboard import BlockedAgentCard
    from remora.ui.components.data import List

    if not blocked:
        return List(
            id="blocked-agents",
            class_="blocked-agents",
            empty_message="No agents waiting for input",
        ).render()

    cards = [BlockedAgentCard(b) for b in blocked]
    return List(
        items=cards,
        id="blocked-agents",
        class_="blocked-agents",
    ).render()


def render_dashboard(state: dict[str, Any], *, bundle_default: str = "") -> str:
    """Render the full dashboard using components."""
    events = state.get("events", [])
    blocked = state.get("blocked", [])
    agent_states = state.get("agent_states", {})
    progress = state.get("progress", {"total": 0, "completed": 0, "failed": 0})
    results = state.get("results", [])
    recent_targets = state.get("recent_targets", [])

    header = Element(
        tag="div",
        content=RawHTML(
            Element(tag="div", content="Remora Dashboard").render()
            + Element(
                tag="div",
                content=f"Agents: {progress['completed']}/{progress['total']}",
                class_="status",
            ).render()
        ),
        class_="header",
    ).render()

    events_panel = Element(
        tag="div",
        content=RawHTML(
            Element(tag="div", content="Events Stream", id="events-header").render()
            + EventsList(events=events).render()
        ),
        id="events-panel",
    ).render()

    graph_launcher_card = GraphLauncher(
        recent_targets=recent_targets,
        bundle_default=bundle_default,
    ).render()

    blocked_card = Card(
        title="Blocked Agents",
        content=RawHTML(render_blocked_list(blocked)),
    ).render()

    status_card = Card(
        title="Agent Status",
        content=AgentStatusList(agent_states=agent_states),
    ).render()

    results_card = Card(
        title="Results",
        content=ResultsList(results=results),
    ).render()

    progress_card = Card(
        title="Graph Execution",
        content=ProgressBar(
            total=progress["total"],
            completed=progress["completed"],
            failed=progress.get("failed", 0),
        ),
    ).render()

    main_panel = Element(
        tag="div",
        content=RawHTML(graph_launcher_card + blocked_card + status_card + results_card + progress_card),
        id="main-panel",
    ).render()

    main = Element(
        tag="div",
        content=RawHTML(events_panel + main_panel),
        class_="main",
    ).render()

    return Element(
        tag="main",
        content=RawHTML(header + main),
        id="remora-root",
    ).render()


__all__ = ["render_dashboard"]
