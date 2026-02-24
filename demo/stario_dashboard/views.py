from datetime import datetime

from stario import asset, at, data
from stario.html import (
    Body,
    Button,
    Div,
    Head,
    Html,
    Input,
    Meta,
    Option,
    Select,
    Link,
    Script,
    Span,
    Title,
)

from .state import DashboardState


def page():
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1.0"}),
            Title("Remora Dashboard"),
            Link({"rel": "stylesheet", "href": "/static/" + asset("css/style.css")}),
            Script({"type": "module", "src": "/static/" + asset("js/datastar.js")}),
        ),
        Body(),
    )


def page_with_content(*children):
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1.0"}),
            Title("Remora Dashboard"),
            Link({"rel": "stylesheet", "href": "/static/" + asset("css/style.css")}),
            Script({"type": "module", "src": "/static/" + asset("js/datastar.js")}),
        ),
        Body(*children),
    )


def event_item_view(event: dict) -> Div:
    timestamp = event.get("timestamp", "")
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M:%S")
        except Exception:
            time_str = "--:--:--"
    else:
        time_str = "--:--:--"

    category = event.get("category", "")
    action = event.get("action", "")
    agent_id = event.get("agent_id", "")
    payload = event.get("payload", {})

    css_class = f"event {category}_{action}"

    return Div(
        {"class": css_class},
        Span({"class": "event-time"}, time_str),
        Span({"class": "event-type"}, f"{category}:{action}"),
        Span({"class": "event-agent"}, f"@{agent_id}") if agent_id else "",
        Div({"class": "event-payload"}, str(payload)) if payload else "",
    )


def events_list_view(events: list[dict]) -> Div:
    if not events:
        return Div({"id": "events-list", "class": "events-list"}, Div({"class": "empty-state"}, "No events yet"))

    return Div(
        {"id": "events-list", "class": "events-list"},
        data.on("load", "setTimeout(() => this.scrollTop = this.scrollHeight, 10)"),
        *[event_item_view(e) for e in reversed(events)],
    )


def blocked_card_view(blocked: dict) -> Div:
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    msg_id = blocked.get("msg_id", "")

    key = f"{agent_id}:{question}".replace(":", "_")

    card = Div(
        {"class": "blocked-agent", "data-key": key},
        Div({"class": "agent-id"}, f"@{agent_id}"),
        Div({"class": "question"}, question),
        Div({"class": "response-form"}),
    )

    if options and len(options) > 0:
        select = Select(
            {"id": f"answer-{key}"},
            data.bind(f"responseDraft.{key}"),
            *[Option({"value": opt}, opt) for opt in options],
        )
        card.children[2].children.append(select)
    else:
        input_elem = Input(
            {
                "id": f"answer-{key}",
                "type": "text",
                "placeholder": "Your response...",
                "autocomplete": "off",
            },
            data.bind(f"responseDraft.{key}"),
        )
        card.children[2].children.append(input_elem)

    card.children.append(Div({}, data.signals({"msg_id": msg_id, "agent_id": agent_id})))

    button = Button(
        {"type": "button"},
        data.on(
            "click",
            f"""
            const draft = $responseDraft?.{key};
            if (draft?.trim()) {{
                @post('/agent/$agent_id/respond', {{question: '{question}', answer: draft}});
                $responseDraft.{key} = '';
            }}
            """,
        ),
        "Send",
    )
    card.children[2].children.append(button)

    return card


def blocked_list_view(blocked: list[dict]) -> Div:
    if not blocked:
        return Div(
            {"id": "blocked-agents", "class": "blocked-agents"},
            Div({"class": "empty-state"}, "No agents waiting for input"),
        )

    return Div(
        {"id": "blocked-agents", "class": "blocked-agents"},
        *[blocked_card_view(b) for b in blocked],
    )


def agent_item_view(agent_id: str, state_info: dict) -> Div:
    state = state_info.get("state", "pending")
    name = state_info.get("name", agent_id)

    return Div(
        {"class": "agent-item"},
        Span({"class": f"state-indicator {state}"}),
        Span({"class": "agent-name"}, name),
        Span({"class": "agent-state"}, state),
    )


def agent_status_view(agent_states: dict) -> Div:
    if not agent_states:
        return Div(
            {"id": "agent-status", "class": "agent-status"},
            Div({"class": "empty-state"}, "No agents running"),
        )

    return Div(
        {"id": "agent-status", "class": "agent-status"},
        *[agent_item_view(aid, info) for aid, info in agent_states.items()],
    )


def result_item_view(result: dict) -> Div:
    agent_id = result.get("agent_id", "")
    content = result.get("content", "")

    return Div(
        {"class": "result-item"},
        Div({"class": "result-agent"}, f"@{agent_id}"),
        Div({"class": "result-content"}, content),
    )


def results_view(results: list[dict]) -> Div:
    if not results:
        return Div(
            {"id": "results", "class": "results"},
            Div({"class": "empty-state"}, "No results yet"),
        )

    return Div(
        {"id": "results", "class": "results"},
        *[result_item_view(r) for r in results],
    )


def progress_bar_view(total: int, completed: int) -> Div:
    percent = int((completed / total) * 100) if total > 0 else 0

    return Div(
        {"id": "execution-progress"},
        Div(
            {"class": "progress-bar"},
            Div(
                {"id": "progress-fill", "class": "progress-fill"},
                data.style("width", f"$progress.completed / $progress.total * 100 + '%'"),
            ),
        ),
        Div(
            {"id": "progress-text", "class": "progress-text"},
            data.text(f"$progress.completed + '/' + $progress.total + ' agents completed'"),
        ),
    )


def dashboard_view(state: DashboardState) -> Html:
    signals = state.get_signals()

    return page_with_content(
        data.signals(signals, ifmissing=True),
        data.init(at.get("/events")),
        Div(
            {"class": "header"},
            Div({}, "Remora Dashboard"),
            Div({"id": "connection-status", "class": "status connected"}, "Connected"),
        ),
        Div(
            {"class": "main"},
            Div(
                {"id": "events-panel"},
                Div({"id": "events-header"}, "Events Stream"),
                events_list_view(signals["events"]),
            ),
            Div(
                {"id": "main-panel"},
                Div(
                    {"class": "card"},
                    Div({}, "Blocked Agents"),
                    blocked_list_view(signals["blocked"]),
                ),
                Div(
                    {"class": "card"},
                    Div({}, "Agent Status"),
                    agent_status_view(signals["agentStates"]),
                ),
                Div(
                    {"class": "card"},
                    Div({}, "Results"),
                    results_view(signals["results"]),
                ),
                Div(
                    {"class": "card"},
                    Div({}, "Graph Execution"),
                    progress_bar_view(signals["progress"]["total"], signals["progress"]["completed"]),
                ),
            ),
        ),
    )
