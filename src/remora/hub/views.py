import html
import json

from datastar_py import attribute_generator as data


def render_tag(tag, content="", **attrs):
    """Simple HTML tag renderer."""
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v)
    if content:
        return f"<{tag} {attr_str}>{content}</{tag}>" if attr_str else f"<{tag}>{content}</{tag}>"
    return f"<{tag} {attr_str}/>" if attr_str else f"<{tag}/>"


def page(title="Remora Hub", *body_content):
    """Base HTML shell with Datastar loaded."""
    body_attrs = data.init("@get('/subscribe)")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body {body_attrs}>
    {"".join(body_content)}
</body>
</html>"""


def event_item_view(event: dict) -> str:
    """Single event in the stream."""
    timestamp = event.get("timestamp", "")[:8] if event.get("timestamp") else "--:--:--"
    category = event.get("category", "")
    action = event.get("action", "")
    agent_id = event.get("agent_id", "")
    payload = event.get("payload", {})

    return render_tag(
        "div",
        content=(
            render_tag("span", content=timestamp, class_="event-time")
            + render_tag("span", content=f"{category}:{action}", class_="event-type")
            + (render_tag("span", content=f"@{agent_id}", class_="event-agent") if agent_id else "")
            + (render_tag("div", content=str(payload), class_="event-payload") if payload else "")
        ),
        class_=f"event {category}_{action}",
    )


def events_list_view(events: list[dict]) -> str:
    """List of events."""
    if not events:
        return render_tag(
            "div",
            id="events-list",
            class_="events-list",
            content=render_tag("div", content="No events yet", class_="empty-state"),
        )

    events_html = "".join(event_item_view(e) for e in reversed(events[-50:]))
    return render_tag("div", id="events-list", class_="events-list", content=events_html)


def blocked_card_view(blocked: dict) -> str:
    """
    BLOCKED AGENT CARD - This is KEY for user interaction!

    Shows:
    - Agent ID and question
    - Options (if multiple choice) OR text input
    - Send button that POSTs to /agent/{agent_id}/respond
    """
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    msg_id = blocked.get("msg_id", "")

    key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")

    # Build response input
    if options and len(options) > 0:
        # Multiple choice - use select
        options_html = "".join(render_tag("option", content=opt, value=opt) for opt in options)
        input_html = render_tag(
            "select", id=f"answer-{key}", content=options_html, **{"data-bind": f"responseDraft.{key}"}
        )
    else:
        # Text input
        input_html = render_tag(
            "input",
            id=f"answer-{key}",
            type="text",
            placeholder="Your response...",
            autocomplete="off",
            **{"data-bind": f"responseDraft.{key}"},
        )

    # Send button - posts to /agent/{agent_id}/respond
    button = render_tag(
        "button",
        content="Send",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": f"""
            const draft = $responseDraft?.{key};
            if (draft?.trim()) {{
                @post('/agent/{agent_id}/respond', {{question: '{question}', answer: draft, msg_id: '{msg_id}'}});
                $responseDraft.{key} = '';
            }}
        """,
        },
    )

    # Assemble the form
    form = render_tag("div", id=f"form-{key}", class_="response-form", content=input_html + button)

    # Add hidden signals for msg_id and agent_id
    signals = render_tag("div", **{"data-signals": f'{{"msg_id": "{msg_id}", "agent_id": "{agent_id}"}}'})

    return render_tag(
        "div",
        class_="blocked-agent",
        **{"data-key": key},
        content=(
            render_tag("div", content=f"@{agent_id}", class_="agent-id")
            + render_tag("div", content=question, class_="question")
            + form
            + signals
        ),
    )


def blocked_list_view(blocked: list[dict]) -> str:
    """List of blocked agents waiting for response."""
    if not blocked:
        return render_tag(
            "div",
            id="blocked-agents",
            class_="blocked-agents",
            content=render_tag("div", content="No agents waiting for input", class_="empty-state"),
        )

    cards = "".join(blocked_card_view(b) for b in blocked)
    return render_tag("div", id="blocked-agents", class_="blocked-agents", content=cards)


def graph_launcher_card_view() -> str:
    """Card that lets users configure and start a graph."""
    defaults = {
        "graphLauncher": {
            "graphId": "",
            "bundle": "default",
            "target": "",
        }
    }
    signals_attr = html.escape(json.dumps(defaults), quote=True)

    graph_id_input = render_tag(
        "input",
        placeholder="Graph ID (required)",
        type="text",
        **{"data-bind": "graphLauncher.graphId"},
    )
    bundle_input = render_tag(
        "input",
        placeholder="Bundle (optional)",
        type="text",
        **{"data-bind": "graphLauncher.bundle"},
    )
    target_input = render_tag(
        "input",
        placeholder="Target description (optional)",
        type="text",
        **{"data-bind": "graphLauncher.target"},
    )

    button = render_tag(
        "button",
        content="Start Graph",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": """
                const graphId = $graphLauncher?.graphId?.trim();
                if (!graphId) {
                    alert('Graph ID is required to launch a graph.');
                    return;
                }
                const payload = {
                    graph_id: graphId,
                    bundle: $graphLauncher?.bundle?.trim() || 'default',
                };
                const targetValue = $graphLauncher?.target?.trim();
                if (targetValue) {
                    payload.target = targetValue;
                }
                @post('/graph/execute', payload);
                $graphLauncher.graphId = '';
            """,
        },
    )

    form = render_tag(
        "div",
        class_="graph-launcher-form",
        content=graph_id_input + bundle_input + target_input + button,
    )

    signals_div = render_tag(
        "div",
        **{
            "data-signals__ifmissing": signals_attr,
            "style": "display:none",
        },
    )

    return render_tag(
        "div",
        class_="card graph-launcher-card",
        content=render_tag("div", content="Launch Graph") + form + signals_div,
    )


def agent_item_view(agent_id: str, state_info: dict) -> str:
    """Single agent status."""
    state = state_info.get("state", "pending")
    name = state_info.get("name", agent_id)

    return render_tag(
        "div",
        class_="agent-item",
        content=(
            render_tag("span", class_=f"state-indicator {state}")
            + render_tag("span", content=name, class_="agent-name")
            + render_tag("span", content=state, class_="agent-state")
        ),
    )


def agent_status_view(agent_states: dict) -> str:
    """All agent statuses."""
    if not agent_states:
        return render_tag(
            "div",
            id="agent-status",
            class_="agent-status",
            content=render_tag("div", content="No agents running", class_="empty-state"),
        )

    items = "".join(agent_item_view(aid, info) for aid, info in agent_states.items())
    return render_tag("div", id="agent-status", class_="agent-status", content=items)


def result_item_view(result: dict) -> str:
    """Single result."""
    agent_id = result.get("agent_id", "")
    content = result.get("content", "")

    return render_tag(
        "div",
        class_="result-item",
        content=(
            render_tag("div", content=f"@{agent_id}", class_="result-agent")
            + render_tag("div", content=content, class_="result-content")
        ),
    )


def results_view(results: list[dict]) -> str:
    """List of results."""
    if not results:
        return render_tag(
            "div",
            id="results",
            class_="results",
            content=render_tag("div", content="No results yet", class_="empty-state"),
        )

    items = "".join(result_item_view(r) for r in results)
    return render_tag("div", id="results", class_="results", content=items)


def progress_bar_view(total: int, completed: int) -> str:
    """Progress bar."""
    percent = int((completed / total) * 100) if total > 0 else 0

    return render_tag(
        "div",
        id="execution-progress",
        content=(
            render_tag(
                "div",
                class_="progress-bar",
                content=render_tag(
                    "div", id="progress-fill", class_="progress-fill", **{"style": f"width: {percent}%"}
                ),
            )
            + render_tag("div", content=f"{completed}/{total} agents completed", class_="progress-text")
        ),
    )


def dashboard_view(view_data: dict) -> str:
    """
    Main dashboard view - complete HTML snapshot.

    This is called on initial load AND on every SSE patch.
    Datastar matches elements by ID and morphs the DOM.
    """
    events = view_data.get("events", [])
    blocked = view_data.get("blocked", [])
    agent_states = view_data.get("agentStates", {})
    progress = view_data.get("progress", {"total": 0, "completed": 0})
    results = view_data.get("results", [])

    header = render_tag(
        "div",
        class_="header",
        content=render_tag("div", content="Remora Hub")
        + render_tag("div", content=f"Agents: {progress['completed']}/{progress['total']}", class_="status"),
    )

    events_panel = render_tag(
        "div",
        id="events-panel",
        content=render_tag("div", id="events-header", content="Events Stream") + events_list_view(events),
    )

    graph_launcher_card = graph_launcher_card_view()

    blocked_card = render_tag(
        "div", class_="card", content=render_tag("div", content="Blocked Agents") + blocked_list_view(blocked)
    )

    status_card = render_tag(
        "div", class_="card", content=render_tag("div", content="Agent Status") + agent_status_view(agent_states)
    )

    results_card = render_tag(
        "div", class_="card", content=render_tag("div", content="Results") + results_view(results)
    )

    progress_card = render_tag(
        "div",
        class_="card",
        content=render_tag("div", content="Graph Execution")
        + progress_bar_view(progress["total"], progress["completed"]),
    )

    main_panel = render_tag(
        "div",
        id="main-panel",
        content=graph_launcher_card + blocked_card + status_card + results_card + progress_card,
    )

    main = render_tag("div", class_="main", content=events_panel + main_panel)

    return page(header + main)
