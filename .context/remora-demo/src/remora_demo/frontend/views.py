"""
Frontend views - using Stario HTML helpers.

These views must match the hub's dashboard_view structure for Datastar
to correctly morph DOM elements by ID.
"""

from stario import at, data
from stario.html import (
    Body,
    Button,
    Div,
    Head,
    Html,
    Input,
    Link,
    Meta,
    Script,
    Title,
    render,
)


def home_view() -> Html:
    """
    Home page - initializes Datastar signals and subscribes to hub.

    The view structure must match the hub's dashboard_view for Datastar
    to correctly morph DOM elements by ID.
    """
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1.0"}),
            Title("Remora Dashboard"),
            Link({"rel": "stylesheet", "href": "/static/css/style.css"}),
            Script(
                {
                    "type": "module",
                    "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
                }
            ),
        ),
        Body(
            data.signals(
                {
                    "selectedAgent": None,
                    "events": [],
                    "blocked": [],
                    "agentStates": {},
                    "progress": {"total": 0, "completed": 0},
                    "results": [],
                    "responseDraft": {},
                    "graphLauncher": {
                        "graphId": "",
                        "bundle": "default",
                        "target": "",
                        "targetPath": "",
                    },
                },
                ifmissing=True,
            ),
            data.init(at.get("/subscribe")),
            Div(
                {"class": "header"},
                Div({}, "Remora Dashboard"),
                Div({"class": "status connected"}, "Connected to hub"),
            ),
            Div(
                {"class": "main"},
                Div(
                    {"id": "events-panel"},
                    Div({"id": "events-header"}, "Events Stream"),
                    Div({"id": "events-list"}, "Loading..."),
                ),
                Div(
                    {"id": "main-panel"},
                    Div(
                        {"class": "card graph-launcher-card"},
                        Div({}, "Launch Graph"),
                        Div(
                            {"class": "graph-launcher-form"},
                            Input(
                                {
                                    "type": "text",
                                    "placeholder": "Graph ID (required)",
                                    "data-bind": "graphLauncher.graphId",
                                }
                            ),
                            Input(
                                {
                                    "type": "text",
                                    "placeholder": "Bundle (optional)",
                                    "data-bind": "graphLauncher.bundle",
                                }
                            ),
                            Input(
                                {
                                    "type": "text",
                                    "placeholder": "Target description (optional)",
                                    "data-bind": "graphLauncher.target",
                                }
                            ),
                            Input(
                                {
                                    "type": "text",
                                    "placeholder": "Target file path (optional)",
                                    "data-bind": "graphLauncher.targetPath",
                                }
                            ),
                            Button(
                                {
                                    "type": "button",
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
                                    const targetPathValue = $graphLauncher?.targetPath?.trim();
                                    if (targetPathValue) {
                                        payload.target_path = targetPathValue;
                                    }
                                    @post('/graph/execute', payload);
                                    $graphLauncher.graphId = '';
                                """,
                                },
                                "Start Graph",
                            ),
                        ),
                    ),
                    Div(
                        {"class": "card"},
                        Div({}, "Blocked Agents"),
                        Div({"id": "blocked-agents"}, "No agents waiting"),
                    ),
                    Div(
                        {"class": "card"},
                        Div({}, "Agent Status"),
                        Div({"id": "agent-status"}, "No agents running"),
                    ),
                    Div(
                        {"class": "card"},
                        Div({}, "Results"),
                        Div({"id": "results"}, "No results yet"),
                    ),
                    Div(
                        {"class": "card"},
                        Div({}, "Graph Execution"),
                        Div({"id": "execution-progress"}, "No execution"),
                    ),
                ),
            ),
        ),
    )


def render_home() -> str:
    """Render the home page to string."""
    return render(home_view())
