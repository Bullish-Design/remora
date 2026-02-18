"""Terminal dashboard for Remora event streams."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import typer
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(help="Render a live dashboard for Remora event streams.")
console = Console()


def _default_cache_dir() -> Path:
    cache_root = os.getenv("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "remora"
    return Path.home() / ".cache" / "remora"


def _default_event_output() -> Path:
    return _default_cache_dir() / "events.jsonl"


def _default_control_file() -> Path:
    return _default_cache_dir() / "events.control"


@dataclass
class AgentState:
    last_event: str = "idle"
    last_ts: float = 0.0
    in_flight: int = 0


@dataclass
class LogEntry:
    timestamp: float
    agent_id: str
    event: str
    detail: str


def _parse_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return time.time()
    return time.time()


def _format_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _format_since(now: float, timestamp: float) -> str:
    if timestamp <= 0:
        return "-"
    return f"{now - timestamp:0.1f}s"


def _make_metrics_panel(
    window_seconds: int,
    model_events: deque[tuple[float, int]],
    in_flight: int,
    agent_count: int,
    now: float,
) -> Panel:
    window_start = now - window_seconds
    while model_events and model_events[0][0] < window_start:
        model_events.popleft()
    total_tokens = sum(tokens for _, tokens in model_events)
    total_requests = len(model_events)
    req_per_sec = total_requests / window_seconds if window_seconds > 0 else 0.0
    tokens_per_sec = total_tokens / window_seconds if window_seconds > 0 else 0.0

    table = Table.grid(padding=1)
    table.add_column(justify="right")
    table.add_column(justify="left")
    table.add_row("Agents", str(agent_count))
    table.add_row("In-flight", str(in_flight))
    table.add_row("Req/sec", f"{req_per_sec:0.2f}")
    table.add_row("Tokens/sec", f"{tokens_per_sec:0.1f}")
    table.add_row("Window", f"{window_seconds}s")
    return Panel(table, title="Throughput")


def _make_agents_table(states: dict[str, AgentState], now: float) -> Table:
    table = Table(title="Agents", show_lines=False)
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("In-flight", justify="right")
    table.add_column("Last", justify="right")
    table.add_column("Last Event")
    for agent_id, state in sorted(states.items()):
        status = "busy" if state.in_flight > 0 else "idle"
        table.add_row(
            agent_id,
            status,
            str(state.in_flight),
            _format_since(now, state.last_ts),
            state.last_event,
        )
    return table


def _make_log_table(entries: deque[LogEntry]) -> Table:
    table = Table(title="Recent Events", show_lines=False)
    table.add_column("Time", width=8)
    table.add_column("Agent", width=24)
    table.add_column("Event", width=16)
    table.add_column("Detail")
    for entry in list(entries)[-30:]:
        table.add_row(_format_time(entry.timestamp), entry.agent_id, entry.event, entry.detail)
    return table


def _format_detail(event: dict[str, Any]) -> str:
    event_type = event.get("event", "")
    if event_type == "model_response":
        tokens = event.get("total_tokens") or event.get("completion_tokens") or 0
        duration = event.get("duration_ms") or "?"
        status = event.get("status", "ok")
        return f"{status} {tokens} tok {duration} ms"
    if event_type == "tool_call":
        return str(event.get("tool_name", ""))
    if event_type == "tool_result":
        status = event.get("status", "ok")
        name = event.get("tool_name", "")
        return f"{name} ({status})"
    if event_type == "agent_error":
        return str(event.get("error", ""))
    return ""


def _read_control_state(control_file: Path) -> dict[str, Any] | None:
    if not control_file.exists():
        return None
    try:
        content = control_file.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _write_control_state(control_file: Path, payload: dict[str, Any]) -> None:
    control_file.parent.mkdir(parents=True, exist_ok=True)
    control_file.write_text(json.dumps(payload), encoding="utf-8")


def _open_stream(input_path: Path | None) -> tuple[Any, bool]:
    if input_path is None or str(input_path) == "-":
        return sys.stdin, False
    input_path.parent.mkdir(parents=True, exist_ok=True)
    if not input_path.exists():
        input_path.touch()
    return input_path.open("r", encoding="utf-8"), True


@app.command()
def main(
    input_path: Path | None = typer.Option(
        None,
        "--input",
        "-i",
        help="Path to JSONL event file, or '-' for stdin.",
    ),
    control_file: Path | None = typer.Option(
        None,
        "--control-file",
        help="Path to the Remora event control file.",
    ),
    window_seconds: int = typer.Option(10, "--window"),
    refresh_seconds: float = typer.Option(0.2, "--refresh"),
    max_log: int = typer.Option(200, "--max-log"),
) -> None:
    use_stdin = input_path is not None and str(input_path) == "-"
    event_output = input_path or _default_event_output()
    control_path = control_file or _default_control_file()
    previous_payload = _read_control_state(control_path) if not use_stdin else None
    previous_enabled = False
    if previous_payload and isinstance(previous_payload.get("enabled"), bool):
        previous_enabled = bool(previous_payload.get("enabled"))
    if not use_stdin:
        _write_control_state(control_path, {"enabled": True, "output": str(event_output)})

    stream, follow = _open_stream(event_output if not use_stdin else Path("-"))
    states: dict[str, AgentState] = {}
    log_entries: deque[LogEntry] = deque(maxlen=max_log)
    model_events: deque[tuple[float, int]] = deque()
    in_flight = 0

    def render() -> Layout:
        now = time.time()
        layout = Layout()
        layout.split_column(
            Layout(name="metrics", size=7),
            Layout(name="agents", ratio=1),
            Layout(name="logs", ratio=2),
        )
        layout["metrics"].update(_make_metrics_panel(window_seconds, model_events, in_flight, len(states), now))
        layout["agents"].update(_make_agents_table(states, now))
        layout["logs"].update(_make_log_table(log_entries))
        return layout

    next_refresh = time.monotonic()
    refresh_interval = max(refresh_seconds, 0.05)

    try:
        with Live(render(), console=console, refresh_per_second=10, screen=False) as live:
            while True:
                line = stream.readline()
                if not line:
                    if not follow:
                        break
                    time.sleep(0.05)
                else:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        payload = {}
                    event_type = payload.get("event") if isinstance(payload, dict) else None
                    if event_type:
                        agent_id = payload.get("agent_id", "unknown")
                        timestamp = _parse_timestamp(payload.get("ts"))
                        state = states.setdefault(agent_id, AgentState())
                        state.last_event = event_type
                        state.last_ts = timestamp
                        if event_type == "model_request":
                            state.in_flight += 1
                            in_flight += 1
                        if event_type == "model_response":
                            if state.in_flight > 0:
                                state.in_flight -= 1
                            if in_flight > 0:
                                in_flight -= 1
                            tokens = payload.get("total_tokens")
                            if tokens is None:
                                tokens = (payload.get("prompt_tokens") or 0) + (payload.get("completion_tokens") or 0)
                            model_events.append((timestamp, int(tokens)))
                        detail = _format_detail(payload)
                        log_entries.append(
                            LogEntry(
                                timestamp=timestamp,
                                agent_id=str(agent_id),
                                event=str(event_type),
                                detail=str(detail)[:120],
                            )
                        )

                now = time.monotonic()
                if now >= next_refresh:
                    live.update(render())
                    next_refresh = now + refresh_interval
    finally:
        if follow:
            stream.close()
        if not use_stdin:
            if previous_payload is not None and previous_enabled:
                _write_control_state(control_path, previous_payload)
            else:
                _write_control_state(control_path, {"enabled": False})


if __name__ == "__main__":
    app()
