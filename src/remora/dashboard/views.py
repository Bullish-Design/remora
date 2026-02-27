"""Dashboard views - Datastar-powered web UI."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from datastar_py import attribute_generator as data
from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from remora.config import RemoraConfig
from remora.context import ContextBuilder
from remora.dashboard.state import DashboardState
from remora.discovery import discover
from remora.executor import GraphExecutor
from remora.event_bus import EventBus
from remora.events import HumanInputResponseEvent
from remora.graph import build_graph
from remora.utils import PathResolver

logger = logging.getLogger(__name__)


def render_tag(tag, content="", **attrs):
    """Simple HTML tag renderer."""
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


def page(title="Remora Dashboard", *body_content):
    """Base HTML shell with Datastar loaded."""
    body_attrs = data.init("@get('/subscribe')")
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{title}</title>
    <script type=\"module\" src=\"https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js\"></script>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .header {{ background: #333; color: white; padding: 20px; margin: -20px -20px 20px -20px; display: flex; justify-content: space-between; }}
        .card {{ background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .events-list, .blocked-agents, .agent-status, .results {{ max-height: 300px; overflow-y: auto; }}
        .event {{ padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
        .event-time {{ color: #666; margin-right: 8px; }}
        .event-type {{ background: #e0e0e0; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
        .blocked-agent {{ background: #fff3cd; padding: 12px; border-radius: 4px; margin-bottom: 8px; }}
        .agent-id {{ font-weight: bold; color: #856404; }}
        .question {{ margin: 8px 0; }}
        .response-form {{ display: flex; gap: 8px; }}
        .response-form input, .response-form select {{ flex: 1; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }}
        .response-form button {{ padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }}
        .state-indicator {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }}
        .state-indicator.started {{ background: #28a745; }}
        .state-indicator.completed {{ background: #17a2b8; }}
        .state-indicator.failed {{ background: #dc3545; }}
        .state-indicator.blocked {{ background: #ffc107; }}
        .empty-state {{ color: #999; text-align: center; padding: 20px; }}
        .progress-bar {{ height: 20px; background: #e0e0e0; border-radius: 10px; overflow: hidden; }}
        .progress-fill {{ height: 100%; background: #28a745; transition: width 0.3s; }}
        .main {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .graph-launcher-form {{ display: grid; gap: 8px; }}
        .graph-launcher-form input {{ padding: 8px; border: 1px solid #ddd; border-radius: 4px; }}
        .recent-targets {{ margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }}
        .recent-label {{ font-size: 12px; color: #666; width: 100%; }}
        .recent-target {{ padding: 4px 8px; border-radius: 999px; border: 1px solid #ddd; background: #f8f8f8; cursor: pointer; font-size: 12px; }}
        @media (max-width: 768px) {{ .main {{ grid-template-columns: 1fr; }} }}
    </style>
    <script>
        (() => {{
            const listId = "target-options";
            const inputId = "target-path";
            const maxItems = 80;

            const escapeHtml = (value) =>
                value.replaceAll("&", "&amp;")
                    .replaceAll("<", "&lt;")
                    .replaceAll(">", "&gt;")
                    .replaceAll('"', "&quot;")
                    .replaceAll("'", "&#39;");

            const updateList = async (prefix) => {{
                const list = document.getElementById(listId);
                if (!list) {{
                    return;
                }}
                try {{
                    const response = await fetch(`/api/targets?prefix=${{encodeURIComponent(prefix || "")}}`);
                    if (!response.ok) {{
                        return;
                    }}
                    const payload = await response.json();
                    const items = Array.isArray(payload.items) ? payload.items.slice(0, maxItems) : [];
                    list.innerHTML = items.map((item) => `<option value="${{escapeHtml(item)}}"></option>`).join("");
                }} catch (_err) {{
                    list.innerHTML = "";
                }}
            }};

            window.remoraTargetLookup = updateList;

            document.addEventListener("input", (event) => {{
                if (event.target && event.target.id === inputId) {{
                    updateList(event.target.value);
                }}
            }});

            document.addEventListener("focusin", (event) => {{
                if (event.target && event.target.id === inputId) {{
                    updateList(event.target.value);
                }}
            }});
        }})();
    </script>
</head>
<body {body_attrs}>
    {"".join(body_content)}
</body>
</html>"""


def event_item_view(event: dict) -> str:
    """Single event in the stream."""
    timestamp = event.get("timestamp", 0)
    if timestamp:
        import time

        timestamp = time.strftime("%H:%M:%S", time.localtime(timestamp))
    else:
        timestamp = "--:--:--"

    event_type = event.get("event_type", "")
    agent_id = event.get("agent_id", "")

    return render_tag(
        "div",
        content=(
            render_tag("span", content=timestamp, class_="event-time")
            + render_tag("span", content=event_type, class_="event-type")
            + (render_tag("span", content=f"@{agent_id}", class_="event-agent") if agent_id else "")
        ),
        class_="event",
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
    """Blocked agent card - shows question and input for human response."""
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    request_id = blocked.get("request_id", "")

    key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")

    if options and len(options) > 0:
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
            type="text",
            placeholder="Your response...",
            autocomplete="off",
            **{"data-bind": f"responseDraft.{key}"},
        )

    button = render_tag(
        "button",
        content="Send",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": f"""
                const draft = $responseDraft?.{key};
                if (draft?.trim()) {{
                    @post('/input', {{request_id: '{request_id}', response: draft}});
                    $responseDraft.{key} = '';
                }}
            """,
        },
    )

    form = render_tag(
        "div",
        id=f"form-{key}",
        class_="response-form",
        content=input_html + button,
    )

    return render_tag(
        "div",
        class_="blocked-agent",
        content=(
            render_tag("div", content=f"@{agent_id}", class_="agent-id")
            + render_tag("div", content=question, class_="question")
            + form
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


def graph_launcher_card_view(recent_targets: list[str] | None = None) -> str:
    """Card that lets users configure and start a graph."""
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
        list="target-options",
        autocomplete="off",
        **{"data-bind": "graphLauncher.target_path"},
    )
    datalist = '<datalist id="target-options"></datalist>'
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
        content=target_input + datalist + bundle_input + button + root_button,
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


def progress_bar_view(total: int, completed: int, failed: int = 0) -> str:
    """Progress bar."""
    percent = int((completed / total) * 100) if total > 0 else 0
    suffix = f" ({failed} failed)" if failed else ""

    return render_tag(
        "div",
        id="execution-progress",
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


def dashboard_view(view_data: dict) -> str:
    """Main dashboard view - complete HTML snapshot."""
    events = view_data.get("events", [])
    blocked = view_data.get("blocked", [])
    agent_states = view_data.get("agent_states", {})
    progress = view_data.get("progress", {"total": 0, "completed": 0, "failed": 0})
    results = view_data.get("results", [])
    recent_targets = view_data.get("recent_targets", [])

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

    return page("Remora Dashboard", header + main)


def create_routes(
    event_bus: EventBus,
    config: RemoraConfig,
    dashboard_state: DashboardState,
    context_builder: ContextBuilder,
    running_tasks: dict[str, asyncio.Task],
    *,
    project_root: Path,
) -> list[Route]:
    """Create Starlette routes for the dashboard."""
    path_resolver = PathResolver(project_root)
    ignored_names = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".tox",
        ".remora",
        ".devenv",
    }

    async def subscribe(request: Request) -> DatastarResponse:
        """SSE endpoint streaming view patches."""

        @datastar_response
        async def event_stream():
            view_data = dashboard_state.get_view_data()
            yield SSE.patch_elements(dashboard_view(view_data))

            async with event_bus.stream() as events:
                async for event in events:
                    view_data = dashboard_state.get_view_data()
                    yield SSE.patch_elements(dashboard_view(view_data))

        return await event_stream()

    async def events(request: Request) -> StreamingResponse:
        """Raw SSE endpoint streaming JSON events."""

        async def event_generator():
            try:
                yield ": open\n\n"
                async with event_bus.stream() as events:
                    async for event in events:
                        event_type = type(event).__name__
                        data = {
                            "event_type": event_type,
                            "graph_id": getattr(event, "graph_id", ""),
                            "agent_id": getattr(event, "agent_id", ""),
                            "timestamp": getattr(event, "timestamp", 0),
                        }
                        yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error in events stream")

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    async def events_ws(websocket: WebSocket) -> None:
        """WebSocket endpoint streaming JSON events."""
        await websocket.accept()
        try:
            async with event_bus.stream() as events:
                async for event in events:
                    payload = {
                        "event_type": type(event).__name__,
                        "graph_id": getattr(event, "graph_id", ""),
                        "agent_id": getattr(event, "agent_id", ""),
                        "timestamp": getattr(event, "timestamp", 0),
                    }
                    await websocket.send_json(payload)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("Error in websocket stream")

    async def index(request: Request) -> HTMLResponse:
        """Render the dashboard page."""
        view_data = dashboard_state.get_view_data()
        return HTMLResponse(dashboard_view(view_data))

    async def list_targets(request: Request) -> JSONResponse:
        """Return target path suggestions relative to project root."""
        prefix = request.query_params.get("prefix", "").strip()
        suggestions = _list_target_suggestions(prefix)
        return JSONResponse({"items": suggestions})

    async def run_agent(request: Request) -> JSONResponse:
        """Trigger graph execution."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}

        target_path = payload.get("target_path", "")
        bundle = payload.get("bundle", "")

        if not target_path:
            return JSONResponse({"error": "target_path is required"}, status_code=400)

        try:
            graph_id = await _trigger_graph(target_path, bundle)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            logger.exception("Failed to start graph")
            return JSONResponse({"error": str(exc)}, status_code=500)

        return JSONResponse({"status": "started", "graph_id": graph_id})

    async def submit_input(request: Request) -> JSONResponse:
        """Submit human input response."""
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        request_id = payload.get("request_id", "")
        response = payload.get("response", "")

        if not request_id or not response:
            return JSONResponse(
                {"error": "request_id and response are required"},
                status_code=400,
            )

        event = HumanInputResponseEvent(request_id=request_id, response=response)
        await event_bus.emit(event)
        return JSONResponse({"status": "submitted"})

    def _build_bundle_mapping() -> dict[str, Path]:
        bundle_root = Path(config.bundles.path)
        mapping: dict[str, Path] = {}
        for name, bundle in config.bundles.mapping.items():
            mapping[name] = bundle_root / bundle
        return mapping

    def _normalize_target(target_path: str) -> Path:
        path_obj = Path(target_path)
        if path_obj.is_absolute():
            resolved = path_obj.resolve()
        else:
            resolved = (project_root / path_obj).resolve()
        if not path_resolver.is_within_project(resolved):
            raise ValueError("target_path must be within the dashboard project root")
        if not resolved.exists():
            raise ValueError("target_path does not exist")
        return resolved

    def _list_target_suggestions(prefix: str) -> list[str]:
        cleaned = prefix.replace("\\", "/").lstrip("/")
        if cleaned.endswith("/"):
            base_dir = (project_root / cleaned).resolve()
            fragment = ""
        else:
            prefix_path = Path(cleaned)
            base_dir = (project_root / prefix_path.parent).resolve()
            fragment = prefix_path.name
        if not base_dir.exists() or not base_dir.is_dir():
            return []
        if not path_resolver.is_within_project(base_dir):
            return []

        fragment_lower = fragment.lower()
        suggestions: list[str] = []
        entries = sorted(
            base_dir.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        for entry in entries:
            if entry.name in ignored_names or entry.name.startswith("."):
                continue
            if fragment_lower and not entry.name.lower().startswith(fragment_lower):
                continue
            try:
                rel = entry.resolve().relative_to(project_root).as_posix()
            except ValueError:
                continue
            if entry.is_dir():
                rel = f"{rel}/"
            suggestions.append(rel)
            if len(suggestions) >= 80:
                break
        return suggestions

    async def _trigger_graph(target_path: str, bundle_name: str) -> str:
        graph_id = uuid.uuid4().hex[:8]
        bundle_mapping = _build_bundle_mapping()

        if not bundle_mapping:
            raise ValueError("No bundle mapping configured")

        target_path_obj = _normalize_target(target_path)
        try:
            rel_target = target_path_obj.relative_to(project_root).as_posix()
        except ValueError:
            rel_target = target_path_obj.as_posix()
        if target_path_obj.is_dir() and not rel_target.endswith("/"):
            rel_target = f"{rel_target}/"
        dashboard_state.record_target(rel_target)
        graph_root = target_path_obj if target_path_obj.is_dir() else target_path_obj.parent
        nodes = discover([target_path_obj])
        agent_nodes = build_graph(nodes, bundle_mapping)

        if bundle_name and bundle_name in bundle_mapping:
            target_bundle = bundle_mapping[bundle_name]
            agent_nodes = [node for node in agent_nodes if node.bundle_path == target_bundle]

        task = asyncio.create_task(_execute_graph(graph_id, agent_nodes, graph_root))
        running_tasks[graph_id] = task

        def _cleanup(_task: asyncio.Task) -> None:
            running_tasks.pop(graph_id, None)

        task.add_done_callback(_cleanup)
        return graph_id

    async def _execute_graph(graph_id: str, agent_nodes: list[Any], project_root: Path) -> None:
        """Run the graph using GraphExecutor."""
        try:
            executor = GraphExecutor(
                config=config,
                event_bus=event_bus,
                context_builder=context_builder,
                project_root=project_root,
            )
            await executor.run(agent_nodes, graph_id)
        except Exception:
            logger.exception("Graph execution failed: %s", graph_id)

    return [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/events", events),
        Route("/api/targets", list_targets),
        WebSocketRoute("/ws", events_ws),
        Route("/run", run_agent, methods=["POST"]),
        Route("/input", submit_input, methods=["POST"]),
    ]
