"""Datastar rendering helpers for Remora's service layer."""

from __future__ import annotations

from typing import Any

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py import attribute_generator as data

from remora.ui.view import render_dashboard


def render_shell(body: str = "", *, title: str = "Remora", init_path: str = "/subscribe") -> str:
    body_attrs = data.init(f"@get('{init_path}')")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
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
        .state-indicator.skipped {{ background: #6c757d; }}
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
</head>
<body {body_attrs}>
    {body}
</body>
</html>"""


def render_patch(state: dict[str, Any], *, bundle_default: str = "") -> str:
    return SSE.patch_elements(render_dashboard(state, bundle_default=bundle_default))


def render_signals(signals: dict[str, Any]) -> str:
    return SSE.patch_signals(signals)


__all__ = ["render_patch", "render_shell", "render_signals"]
