"""UI rendering helpers for the Datastar HTML view."""

from __future__ import annotations

import html
import json
from typing import Any


def render_tag(tag: str, content: str = "", **attrs: Any) -> str:
    normalized_attrs: list[str] = []
    for key, value in attrs.items():
        if value is None or value == "":
            continue
        if key.endswith("_") and key[:-1] in ("class", "for"):
            key = key[:-1]
        normalized_attrs.append(f'{key}="{value}"')
    attr_str = " ".join(normalized_attrs)
    if content:
        return f"<{tag} {attr_str}>{content}</{tag}>" if attr_str else f"<{tag}>{content}</{tag}>"
    return f"<{tag} {attr_str}/>" if attr_str else f"<{tag}/>"


def _escape_js_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def event_item_view(event: dict[str, Any]) -> str:
    timestamp = event.get("timestamp", 0)
    if timestamp:
        import time

        timestamp = time.strftime("%H:%M:%S", time.localtime(timestamp))
    else:
        timestamp = "--:--:--"

    event_type = event.get("type", "")
    agent_id = event.get("agent_id", "")
    kind = event.get("kind", "")
    label = f"{kind}:{event_type}" if kind else event_type

    return render_tag(
        "div",
        content=(
            render_tag("span", content=str(timestamp), class_="event-time")
            + render_tag("span", content=label, class_="event-type")
            + (render_tag("span", content=f"@{agent_id}", class_="event-agent") if agent_id else "")
        ),
        class_="event",
    )


def events_list_view(events: list[dict[str, Any]]) -> str:
    if not events:
        return render_tag(
            "div",
            id="events-list",
            class_="events-list",
            content=render_tag("div", content="No events yet", class_="empty-state"),
        )

    events_html = "".join(event_item_view(e) for e in reversed(events[-50:]))
    return render_tag("div", id="events-list", class_="events-list", content=events_html)


def blocked_card_view(blocked: dict[str, Any]) -> str:
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    request_id = blocked.get("request_id", "")

    key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")

    if options:
        options_html = "".join(render_tag("option", content=opt, value=opt) for opt in options)
        input_html = render_tag(
            "select",
            id=f"answer-{key}",
            content=options_html,
            **{"data-bind": f"responseDraft.{key}"},
        )
    else:
        input_html = render_tag(
            "input",
            id=f"answer-{key}",
            placeholder="Your response",
            **{"data-bind": f"responseDraft.{key}"},
        )

    button = render_tag(
        "button",
        content="Submit",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": f"""
                const draft = $responseDraft?.{key}?.trim();
                if (!draft) {{
                    alert('Response required.');
                    return;
                }}
                @post('/input', {{request_id: '{request_id}', response: draft}});
            """,
        },
    )

    form = render_tag("div", class_="response-form", content=input_html + button)

    return render_tag(
        "div",
        class_="blocked-agent",
        content=(
            render_tag("div", content=f"Agent: {html.escape(agent_id)}", class_="agent-id")
            + render_tag("div", content=html.escape(question), class_="question")
            + form
        ),
    )


def blocked_list_view(blocked: list[dict[str, Any]]) -> str:
    if not blocked:
        return render_tag(
            "div",
            id="blocked-agents",
            class_="blocked-agents",
            content=render_tag("div", content="No agents waiting for input", class_="empty-state"),
        )

    cards = "".join(blocked_card_view(b) for b in blocked)
    return render_tag("div", id="blocked-agents", class_="blocked-agents", content=cards)


def graph_launcher_card_view(recent_targets: list[str] | None = None) -> str:
    defaults = {
        "graphLauncher": {
            "target_path": "",
            "bundle": "lint",
        }
    }
    signals_attr = html.escape(json.dumps(defaults), quote=True)

    target_input = render_tag(
        "input",
        placeholder="Target path (file or directory)",
        type="text",
        id="target-path",
        autocomplete="off",
        **{"data-bind": "graphLauncher.target_path"},
    )
    bundle_input = render_tag(
        "input",
        placeholder="Bundle name (e.g., lint, docstring)",
        type="text",
        **{"data-bind": "graphLauncher.bundle"},
    )

    button = render_tag(
        "button",
        content="Run Graph",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": """
                const target = $graphLauncher?.target_path?.trim();
                const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                if (!target) {
                    alert('Target path is required.');
                    return;
                }
                @post('/run', {target_path: target, bundle: bundle});
            """,
        },
    )
    root_button = render_tag(
        "button",
        content="Run Root Graph",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": """
                const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                @post('/run', {target_path: '.', bundle: bundle});
            """,
        },
    )

    form = render_tag(
        "div",
        class_="graph-launcher-form",
        content=target_input + bundle_input + button + root_button,
    )

    signals_div = render_tag(
        "div",
        **{
            "data-signals__ifmissing": signals_attr,
            "style": "display:none",
        },
    )

    recent_targets = recent_targets or []
    recent_buttons = "".join(
        render_tag(
            "button",
            content=html.escape(target),
            type="button",
            class_="recent-target",
            **{
                "data-on": "click",
                "data-on-click": f"$graphLauncher.target_path = '{_escape_js_string(target)}';",
            },
        )
        for target in recent_targets
    )
    recent_panel = ""
    if recent_buttons:
        recent_panel = render_tag(
            "div",
            class_="recent-targets",
            content=render_tag("div", content="Recent targets", class_="recent-label") + recent_buttons,
        )

    return render_tag(
        "div",
        class_="card graph-launcher-card",
        content=render_tag("div", content="Run Agent Graph") + form + recent_panel + signals_div,
    )


def agent_item_view(agent_id: str, state_info: dict[str, Any]) -> str:
    state = state_info.get("state", "pending")
    name = state_info.get("name", agent_id)

    return render_tag(
        "div",
        class_="agent-item",
        content=(
            render_tag("span", content="", class_=f"state-indicator {state}")
            + render_tag("span", content=html.escape(name), class_="agent-name")
        ),
    )


def agent_status_view(agent_states: dict[str, dict[str, Any]]) -> str:
    if not agent_states:
        return render_tag(
            "div",
            id="agent-status",
            class_="agent-status",
            content=render_tag("div", content="No agents started yet", class_="empty-state"),
        )

    agents_html = "".join(agent_item_view(agent_id, info) for agent_id, info in agent_states.items())
    return render_tag("div", id="agent-status", class_="agent-status", content=agents_html)


def results_view(results: list[dict[str, Any]]) -> str:
    if not results:
        return render_tag(
            "div",
            id="results-list",
            class_="results",
            content=render_tag("div", content="No results yet", class_="empty-state"),
        )

    items = []
    for result in results[:10]:
        items.append(
            render_tag(
                "div",
                class_="result-item",
                content=(
                    render_tag("div", content=html.escape(result.get("agent_id", "")), class_="result-agent")
                    + render_tag("div", content=html.escape(result.get("content", "")), class_="result-content")
                ),
            )
        )

    return render_tag("div", id="results-list", class_="results", content="".join(items))


def progress_bar_view(total: int, completed: int, failed: int = 0) -> str:
    if total <= 0:
        percent = 0
    else:
        percent = min(100, int((completed / total) * 100))

    suffix = f" ({failed} failed)" if failed else ""
    return render_tag(
        "div",
        class_="progress-container",
        content=(
            render_tag(
                "div",
                class_="progress-bar",
                content=render_tag(
                    "div",
                    id="progress-fill",
                    class_="progress-fill",
                    **{"style": f"width: {percent}%"},
                ),
            )
            + render_tag("div", content=f"{completed}/{total} agents completed{suffix}", class_="progress-text")
        ),
    )


def render_dashboard(state: dict[str, Any]) -> str:
    events = state.get("events", [])
    blocked = state.get("blocked", [])
    agent_states = state.get("agent_states", {})
    progress = state.get("progress", {"total": 0, "completed": 0, "failed": 0})
    results = state.get("results", [])
    recent_targets = state.get("recent_targets", [])

    header = render_tag(
        "div",
        class_="header",
        content=render_tag("div", content="Remora Dashboard")
        + render_tag("div", content=f"Agents: {progress['completed']}/{progress['total']}", class_="status"),
    )

    events_panel = render_tag(
        "div",
        id="events-panel",
        content=render_tag("div", id="events-header", content="Events Stream") + events_list_view(events),
    )

    graph_launcher_card = graph_launcher_card_view(recent_targets)

    blocked_card = render_tag(
        "div",
        class_="card",
        content=render_tag("div", content="Blocked Agents") + blocked_list_view(blocked),
    )

    status_card = render_tag(
        "div",
        class_="card",
        content=render_tag("div", content="Agent Status") + agent_status_view(agent_states),
    )

    results_card = render_tag(
        "div",
        class_="card",
        content=render_tag("div", content="Results") + results_view(results),
    )

    progress_card = render_tag(
        "div",
        class_="card",
        content=render_tag("div", content="Graph Execution")
        + progress_bar_view(progress["total"], progress["completed"], progress.get("failed", 0)),
    )

    main_panel = render_tag(
        "div",
        id="main-panel",
        content=graph_launcher_card + blocked_card + status_card + results_card + progress_card,
    )

    main = render_tag("div", class_="main", content=events_panel + main_panel)

    return render_tag("main", header + main, id="remora-root")


__all__ = ["render_dashboard", "render_tag"]
