"""Rich-based dashboard for AST Summary events."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from demo.events import EVENT_FILE


@dataclass
class LogEntry:
    timestamp: float
    event: str
    node: str
    node_type: str
    message: str
    summary: str = ""


def _format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S.%f")[:-3]


def _create_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="status", size=12),
        Layout(name="log"),
    )
    return layout


def _render_log(entries: list[LogEntry]) -> Panel:
    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("Time", width=10, style="dim")
    table.add_column("Event", width=16)
    table.add_column("Type", width=10)
    table.add_column("Node", width=14)
    table.add_column("Message", width=80, overflow="fold")

    for entry in entries[-30:]:
        event_color = _get_event_color(entry.event)
        time_str = _format_time(entry.timestamp)
        message = entry.message
        if entry.summary:
            message = f"{entry.message} → {entry.summary[:100]}..."

        table.add_row(
            time_str,
            Text(entry.event.upper(), style=event_color),
            Text(entry.node_type, style="cyan"),
            Text(entry.node, style="bold white"),
            Text(message, style="white"),
        )

    return Panel(table, title="Event Log", border_style="blue", padding=(0, 1))


def _get_event_color(event: str) -> str:
    colors = {
        "start": "green",
        "parsed": "cyan",
        "workspace_provision": "yellow",
        "summarizing": "magenta bold",
        "llm_request": "blue bold",
        "llm_response": "green bold",
        "llm_error": "red bold",
        "done": "green bold",
        "complete": "green bold reverse",
        "error": "red bold",
    }
    return colors.get(event, "white")


def _render_status(entries: list[LogEntry]) -> Panel:
    node_status: dict[str, str] = {}

    for entry in entries:
        node_key = f"{entry.node_type}:{entry.node}"
        if entry.event == "done":
            node_status[node_key] = "done"
        elif entry.event == "summarizing" and node_key not in node_status:
            node_status[node_key] = "in_progress"
        elif entry.event == "workspace_provision" and node_key not in node_status:
            node_status[node_key] = "pending"

    completed = sum(1 for s in node_status.values() if s == "done")
    in_progress = sum(1 for s in node_status.values() if s == "in_progress")
    pending = sum(1 for s in node_status.values() if s == "pending")

    table = Table.grid(padding=1)
    table.add_column()
    table.add_column(justify="right")
    table.add_row("Total Nodes", str(len(node_status)))
    table.add_row("Completed", Text(str(completed), style="green"))
    table.add_row("In Progress", Text(str(in_progress), style="magenta bold"))
    table.add_row("Pending", Text(str(pending), style="yellow"))

    if entries:
        last_event = entries[-1]
        table.add_row("")
        table.add_row("Last Event", "")
        table.add_row("Node", Text(last_event.node, style="bold"))
        table.add_row("Status", Text(last_event.event, style=_get_event_color(last_event.event)))

    return Panel(table, title="Status", border_style="green", padding=(0, 1))


def _render_header() -> Panel:
    return Panel(
        Text("AST Summary Dashboard", justify="center", style="bold cyan"),
        style="on blue",
        padding=(0, 0),
    )


def tail_events() -> list[LogEntry]:
    entries: list[LogEntry] = []

    if not EVENT_FILE.exists():
        return entries

    with EVENT_FILE.open("r", encoding="utf-8") as f:
        f.seek(0)
        for line in f:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            entries.append(
                LogEntry(
                    timestamp=data.get("timestamp", time.time()),
                    event=data.get("event", "unknown"),
                    node=data.get("node", ""),
                    node_type=data.get("type", ""),
                    message=data.get("message", ""),
                    summary=data.get("summary", ""),
                )
            )

    return entries


class AstDashboardApp:
    """Rich-based dashboard for AST Summary events."""

    def __init__(self, event_file: Path | None = None) -> None:
        self.event_file = event_file or EVENT_FILE
        self.console = Console()
        self.last_count = 0

    def run(self) -> None:
        """Run the dashboard."""
        with Live(_create_layout(), console=self.console, refresh_per_second=5, screen=True) as live:
            while True:
                entries = tail_events()

                layout = _create_layout()
                layout["header"].update(_render_header())
                layout["log"].update(_render_log(entries))
                layout["status"].update(_render_status(entries))

                live.update(layout)

                time.sleep(0.2)


def run_dashboard() -> None:
    """Entry point for the dashboard."""
    app = AstDashboardApp()
    app.run()


if __name__ == "__main__":
    run_dashboard()
