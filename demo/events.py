"""Event emitting for AST Summary dashboard."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

EVENT_FILE = Path(".ast_summary_events.jsonl")


def set_event_file(path: Path) -> None:
    """Set the event file path (useful for testing)."""
    global EVENT_FILE
    EVENT_FILE = path


def emit_event(
    event_type: str,
    node_name: str,
    node_type: str,
    message: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit an event for the dashboard to ingest."""
    if extra is None:
        extra = {}
    payload = {
        "timestamp": time.time(),
        "event": event_type,
        "node": node_name,
        "type": node_type,
        "message": message,
        **extra,
    }
    EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def clear_events() -> None:
    """Clear the event file."""
    if EVENT_FILE.exists():
        EVENT_FILE.unlink()
