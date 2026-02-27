"""Component demo app for Remora UI."""

from __future__ import annotations

import uuid

from datastar_py import attribute_generator as data
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route

from remora.adapters.starlette import create_app as create_remora_app
from remora.core.container import RemoraContainer
from remora.core.events import HumanInputRequestEvent
from remora.service.api import RemoraService
from remora.ui.components import (
    AgentStatusList,
    Button,
    Card,
    Container,
    EventsList,
    FlexRow,
    Grid,
    Input,
    List,
    ListItem,
    Panel,
    ProgressBar,
    ResultsList,
    Select,
    StatusBadge,
)
from remora.ui.components.base import Element, RawHTML
from remora.ui.view import render_dashboard


def create_demo_app(*, config_path: str | None = None, project_root: str | None = None) -> Starlette:
    container = RemoraContainer.create(
        config_path=config_path,
        project_root=project_root,
    )
    service = RemoraService(container=container)
    remora_app = create_remora_app(service)

    async def demo_index(_request: Request) -> HTMLResponse:
        hero = Element(
            tag="div",
            content=RawHTML(
                Element(tag="div", content="Remora UI Component Demo", class_="hero-title").render()
                + Element(
                    tag="div",
                    content="Live pages powered by the real Remora backend.",
                    class_="hero-subtitle",
                ).render()
            ),
            class_="hero",
        ).render()

        tiles = Grid(
            columns="repeat(auto-fit, minmax(260px, 1fr))",
            gap="1.25rem",
            children=[
                Card(
                    title="Dashboard",
                    content=RawHTML(
                        Element(
                            tag="div",
                            content="Live event stream + graph controls.",
                            class_="tile-copy",
                        ).render()
                        + _link_button("Open dashboard", "/demo/dashboard")
                    ),
                    class_="card tile",
                ),
                Card(
                    title="Component Lab",
                    content=RawHTML(
                        Element(
                            tag="div",
                            content="Every component with live data bindings.",
                            class_="tile-copy",
                        ).render()
                        + _link_button("Explore components", "/demo/components")
                    ),
                    class_="card tile",
                ),
                Card(
                    title="Tool Call Observatory",
                    content=RawHTML(
                        Element(
                            tag="div",
                            content="Realtime tool/model event feed.",
                            class_="tile-copy",
                        ).render()
                        + _link_button("Open observatory", "/demo/observatory")
                    ),
                    class_="card tile",
                ),
            ],
        ).render()

        body = Container(
            class_="page",
            children=[
                hero,
                tiles,
            ],
        ).render()

        return HTMLResponse(render_demo_shell(body, title="Remora UI Demo"))

    async def demo_dashboard(_request: Request) -> HTMLResponse:
        state = service.ui_snapshot()
        dashboard = render_dashboard(state, bundle_default=_bundle_default(service))
        body = RawHTML(_nav() + dashboard).render()
        return HTMLResponse(render_demo_shell(body, title="Remora Demo Dashboard", init_path="/subscribe"))

    async def demo_components(_request: Request) -> HTMLResponse:
        state = service.ui_snapshot()
        config = service.config_snapshot().to_dict()
        progress = state.get("progress", {"total": 0, "completed": 0, "failed": 0})

        status_row = FlexRow(
            gap="0.75rem",
            children=[
                RawHTML(StatusBadge("started", "Running").render()),
                RawHTML(StatusBadge("completed", "Done").render()),
                RawHTML(StatusBadge("failed", "Failed").render()),
                RawHTML(StatusBadge("skipped", "Skipped").render()),
            ],
        ).render()

        bundles = config.get("bundles", {}).get("mapping", {})
        bundle_items = [
            ListItem(
                content=RawHTML(
                    Element(tag="span", content=key, class_="bundle-key").render()
                    + Element(tag="span", content=value, class_="bundle-value").render()
                ),
                class_="bundle-item",
            )
            for key, value in bundles.items()
        ]

        control_panel = Panel(
            header="Control Deck",
            content=RawHTML(
                "".join(
                    [
                        Element(tag="div", content="Target path", class_="control-label").render(),
                        Input(
                            id="demo-target",
                            attrs={"placeholder": "src/", "type": "text"},
                        ).render(),
                        Element(tag="div", content="Bundle", class_="control-label").render(),
                        Select(
                            id="demo-bundle",
                            options=list(bundles.keys()) or ["function"],
                        ).render(),
                        Button(
                            label="Plan Graph",
                            id="demo-plan-btn",
                            attrs={"type": "button"},
                            class_="button primary",
                        ).render(),
                        Button(
                            label="Run Graph",
                            id="demo-run-btn",
                            attrs={"type": "button"},
                            class_="button accent",
                        ).render(),
                        Button(
                            label="Emit Blocked Prompt",
                            id="demo-block-btn",
                            attrs={"type": "button"},
                            class_="button ghost",
                        ).render(),
                        Element(tag="pre", content="", id="demo-plan-output", class_="code-block").render(),
                        Element(tag="div", content="", id="demo-run-output", class_="run-output").render(),
                    ]
                )
            ),
            id="control-panel",
        ).render()

        data_panel = Grid(
            gap="1.25rem",
            children=[
                Card(
                    title="Events",
                    content=EventsList(events=state.get("events", [])).render(),
                ),
                Card(
                    title="Agent Status",
                    content=AgentStatusList(agent_states=state.get("agent_states", {})).render(),
                ),
                Card(
                    title="Results",
                    content=ResultsList(results=state.get("results", [])).render(),
                ),
                Card(
                    title="Progress",
                    content=ProgressBar(
                        total=progress.get("total", 0),
                        completed=progress.get("completed", 0),
                        failed=progress.get("failed", 0),
                    ).render(),
                ),
            ],
        ).render()

        layout_panel = Grid(
            gap="1.25rem",
            children=[
                Card(
                    title="Layout Tokens",
                    content=RawHTML(
                        Element(tag="div", content="Container + Grid + FlexRow", class_="tile-copy").render()
                        + status_row
                    ),
                ),
                Card(
                    title="Bundle Mapping",
                    content=List(
                        items=bundle_items,
                        empty_message="No bundles configured",
                    ).render(),
                ),
            ],
        ).render()

        body = Container(
            class_="page",
            children=[
                RawHTML(_nav()),
                Element(tag="div", content="Component Lab", class_="page-title").render(),
                layout_panel,
                control_panel,
                data_panel,
            ],
        ).render()

        script = """
        <script>
        const targetInput = document.getElementById('demo-target');
        const bundleSelect = document.getElementById('demo-bundle');
        const planBtn = document.getElementById('demo-plan-btn');
        const runBtn = document.getElementById('demo-run-btn');
        const blockBtn = document.getElementById('demo-block-btn');
        const planOutput = document.getElementById('demo-plan-output');
        const runOutput = document.getElementById('demo-run-output');

        async function postJson(path, payload) {
            const response = await fetch(path, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            return {ok: response.ok, data};
        }

        planBtn.addEventListener('click', async () => {
            planOutput.textContent = 'Planning...';
            const target = (targetInput.value || '').trim();
            if (!target) {
                planOutput.textContent = 'Target path is required.';
                return;
            }
            const bundle = (bundleSelect.value || '').trim();
            const result = await postJson('/plan', {target_path: target, bundle});
            planOutput.textContent = JSON.stringify(result.data, null, 2);
        });

        runBtn.addEventListener('click', async () => {
            runOutput.textContent = 'Starting run...';
            const target = (targetInput.value || '').trim();
            if (!target) {
                runOutput.textContent = 'Target path is required.';
                return;
            }
            const bundle = (bundleSelect.value || '').trim();
            const result = await postJson('/run', {target_path: target, bundle});
            runOutput.textContent = result.ok
                ? `Run started: ${result.data.graph_id}`
                : `Run failed: ${result.data.error || 'unknown error'}`;
        });

        blockBtn.addEventListener('click', async () => {
            runOutput.textContent = 'Emitting blocked prompt...';
            const result = await postJson('/demo/emit/block', {question: 'Approve next step?'});
            runOutput.textContent = result.ok
                ? `Blocked prompt created: ${result.data.request_id}`
                : 'Failed to emit blocked prompt.';
        });
        </script>
        """

        return HTMLResponse(render_demo_shell(body + script, title="Component Lab"))

    async def demo_observatory(_request: Request) -> HTMLResponse:
        state = service.ui_snapshot()
        events_list = EventsList(events=state.get("events", [])).render()

        feed = Card(
            title="Live Tool/Model Feed",
            content=RawHTML(
                Element(tag="div", content="Awaiting events...", id="observatory-status", class_="tile-copy").render()
                + Element(tag="div", content=events_list, id="observatory-list").render()
            ),
        ).render()

        stats = FlexRow(
            gap="1rem",
            children=[
                _stat_chip("Tools", "0", "tool-count"),
                _stat_chip("Models", "0", "model-count"),
                _stat_chip("Turns", "0", "turn-count"),
            ],
        ).render()

        body = Container(
            class_="page",
            children=[
                RawHTML(_nav()),
                Element(tag="div", content="Tool Call Observatory", class_="page-title").render(),
                stats,
                feed,
            ],
        ).render()

        script = """
        <script>
        const listEl = document.getElementById('observatory-list');
        const statusEl = document.getElementById('observatory-status');
        const toolCount = document.getElementById('tool-count');
        const modelCount = document.getElementById('model-count');
        const turnCount = document.getElementById('turn-count');
        const counts = {tool: 0, model: 0, turn: 0};

        function updateCounts() {
            toolCount.textContent = counts.tool.toString();
            modelCount.textContent = counts.model.toString();
            turnCount.textContent = counts.turn.toString();
        }

        const source = new EventSource('/events');
        source.onmessage = (event) => {
            if (!event.data) {
                return;
            }
            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (err) {
                return;
            }
            const kind = payload.kind || 'event';
            if (!['tool', 'model', 'turn'].includes(kind)) {
                return;
            }
            counts[kind] += 1;
            updateCounts();
            statusEl.textContent = 'Streaming live events...';
            const line = document.createElement('div');
            line.className = 'event';
            line.textContent = `${kind.toUpperCase()} :: ${payload.type}`;
            listEl.prepend(line);
        };
        </script>
        """

        return HTMLResponse(render_demo_shell(body + script, title="Tool Call Observatory"))

    async def emit_blocked(request: Request) -> JSONResponse:
        payload = await request.json() if request.method == "POST" else {}
        question = str(payload.get("question", "Need confirmation"))
        graph_id = str(payload.get("graph_id", "demo-graph"))
        agent_id = str(payload.get("agent_id", "demo-agent"))
        request_id = str(payload.get("request_id", uuid.uuid4().hex[:8]))

        event = HumanInputRequestEvent(
            graph_id=graph_id,
            agent_id=agent_id,
            request_id=request_id,
            question=question,
        )

        if container.event_store is not None:
            await container.event_store.append(graph_id, event)
        await service.event_bus.emit(event)

        return JSONResponse({"request_id": request_id})

    routes = [
        Route("/demo", demo_index),
        Route("/demo/dashboard", demo_dashboard),
        Route("/demo/components", demo_components),
        Route("/demo/observatory", demo_observatory),
        Route("/demo/emit/block", emit_blocked, methods=["POST"]),
        Mount("/", app=remora_app),
    ]

    return Starlette(routes=routes)


def render_demo_shell(body: str, *, title: str, init_path: str | None = None) -> str:
    body_attrs = ""
    if init_path:
        body_attrs = data.init(f"@get('{init_path}')")
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{title}</title>
    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
    <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
    <link href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;600;700&family=IBM+Plex+Sans:wght@400;600&display=swap\" rel=\"stylesheet\">
    <script type=\"module\" src=\"https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js\"></script>
    <style>
        :root {
            --ink: #1a1b1f;
            --paper: #fdf7f0;
            --accent: #f0522b;
            --accent-2: #0bb5a8;
            --accent-3: #f6c945;
            --card: #ffffff;
            --muted: #6a6f7a;
            --line: #e6e0d8;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: 'Space Grotesk', 'IBM Plex Sans', sans-serif;
            color: var(--ink);
            background: radial-gradient(circle at top left, #fff6e6 0%, #fdf7f0 45%, #f7f7ff 100%);
            min-height: 100vh;
        }
        body::before {
            content: "";
            position: fixed;
            inset: 0;
            background: radial-gradient(circle at 10% 20%, rgba(11, 181, 168, 0.15), transparent 40%),
                        radial-gradient(circle at 80% 10%, rgba(240, 82, 43, 0.18), transparent 40%),
                        radial-gradient(circle at 80% 80%, rgba(246, 201, 69, 0.2), transparent 45%);
            pointer-events: none;
        }
        .demo-nav {
            position: sticky;
            top: 0;
            z-index: 20;
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(14px);
            border-bottom: 1px solid var(--line);
            padding: 0.75rem 2rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .nav-links { display: flex; gap: 1rem; }
        .nav-links a {
            text-decoration: none;
            color: var(--ink);
            font-weight: 600;
            padding: 0.35rem 0.8rem;
            border-radius: 999px;
            background: rgba(240, 82, 43, 0.08);
        }
        .nav-brand {
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .page { padding: 2.5rem 3rem 4rem; position: relative; }
        .page-title { font-size: 2rem; font-weight: 700; margin-bottom: 1.25rem; }
        .hero { margin-bottom: 2.5rem; }
        .hero-title { font-size: clamp(2.4rem, 3vw, 3.3rem); font-weight: 700; }
        .hero-subtitle { color: var(--muted); margin-top: 0.75rem; font-size: 1.05rem; }
        .card {
            background: var(--card);
            border-radius: 16px;
            padding: 1.25rem;
            box-shadow: 0 14px 30px rgba(30, 30, 30, 0.08);
            border: 1px solid var(--line);
            animation: rise 0.6s ease both;
        }
        .card-title { font-weight: 600; margin-bottom: 0.75rem; }
        .tile-copy { color: var(--muted); font-size: 0.95rem; margin-bottom: 1rem; }
        .button { padding: 0.6rem 1rem; border-radius: 999px; border: none; cursor: pointer; font-weight: 600; }
        .button.primary { background: var(--accent-2); color: white; }
        .button.accent { background: var(--accent); color: white; }
        .button.ghost { background: rgba(26, 27, 31, 0.08); }
        .events-list, .blocked-agents, .agent-status, .results { max-height: 260px; overflow-y: auto; }
        .event { padding: 0.55rem 0; border-bottom: 1px dashed var(--line); font-size: 0.85rem; }
        .event-time { color: var(--muted); margin-right: 0.5rem; }
        .event-type { background: rgba(11, 181, 168, 0.15); padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; }
        .response-form { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
        .response-form input, .response-form select {
            flex: 1;
            padding: 0.5rem;
            border: 1px solid var(--line);
            border-radius: 8px;
        }
        .state-indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .state-indicator.started { background: var(--accent-2); }
        .state-indicator.completed { background: #3d7fef; }
        .state-indicator.failed { background: var(--accent); }
        .state-indicator.skipped { background: #8a8f98; }
        .empty-state { color: var(--muted); text-align: center; padding: 1rem; }
        .progress-bar { height: 14px; background: #f0eee9; border-radius: 999px; overflow: hidden; }
        .progress-fill { height: 100%; background: var(--accent-2); transition: width 0.3s; }
        .main { display: grid; grid-template-columns: 1.1fr 1fr; gap: 1.5rem; }
        .graph-launcher-form { display: grid; gap: 0.5rem; }
        .graph-launcher-form input { padding: 0.5rem; border: 1px solid var(--line); border-radius: 8px; }
        .recent-targets { margin-top: 0.75rem; display: flex; flex-wrap: wrap; gap: 6px; }
        .recent-target { padding: 4px 10px; border-radius: 999px; border: 1px solid var(--line); background: #f9f7f3; cursor: pointer; font-size: 12px; }
        .bundle-item { display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px dashed var(--line); }
        .bundle-key { font-weight: 600; }
        .bundle-value { color: var(--muted); }
        .control-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-top: 0.5rem; }
        .code-block { background: #0f172a; color: #f8fafc; padding: 1rem; border-radius: 12px; font-size: 0.75rem; overflow: auto; min-height: 120px; }
        .run-output { margin-top: 0.75rem; font-weight: 600; }
        .stat-chip { padding: 0.6rem 1rem; border-radius: 999px; background: rgba(11, 181, 168, 0.15); font-weight: 600; }
        .stat-chip strong { font-size: 1.1rem; margin-left: 0.35rem; }
        @keyframes rise {
            from { transform: translateY(8px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        @media (max-width: 900px) {
            .page { padding: 2rem 1.5rem; }
            .main { grid-template-columns: 1fr; }
            .demo-nav { flex-direction: column; gap: 0.75rem; }
        }
    </style>
</head>
<body {body_attrs}>
    {body}
</body>
</html>"""


def _nav() -> str:
    return Element(
        tag="nav",
        content=RawHTML(
            Element(tag="div", content="REMORA DEMO", class_="nav-brand").render()
            + Element(
                tag="div",
                content=RawHTML(
                    "".join(
                        [
                            _nav_link("/demo", "Home"),
                            _nav_link("/demo/dashboard", "Dashboard"),
                            _nav_link("/demo/components", "Components"),
                            _nav_link("/demo/observatory", "Observatory"),
                        ]
                    )
                ),
                class_="nav-links",
            ).render()
        ),
        class_="demo-nav",
    ).render()


def _nav_link(path: str, label: str) -> str:
    return Element(tag="a", content=label, attrs={"href": path}).render()


def _link_button(label: str, path: str) -> str:
    return Element(
        tag="a",
        content=label,
        attrs={"href": path},
        class_="button primary",
    ).render()


def _stat_chip(label: str, value: str, element_id: str) -> str:
    return Element(
        tag="div",
        content=RawHTML(f"{label} <strong id=\"{element_id}\">{value}</strong>"),
        class_="stat-chip",
    ).render()


def _bundle_default(service: RemoraService) -> str:
    snapshot = service.config_snapshot().to_dict()
    mapping = snapshot.get("bundles", {}).get("mapping", {})
    if isinstance(mapping, dict) and mapping:
        return next(iter(mapping))
    return ""


__all__ = ["create_demo_app"]
