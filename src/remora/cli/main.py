"""Remora CLI entry points."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid
from pathlib import Path

import click

from remora.adapters.starlette import create_app
from remora.core.config import ConfigError, load_config
from remora.core.events import GraphCompleteEvent, GraphErrorEvent
from remora.models import RunRequest
from remora.service.api import RemoraService
from remora.ui.projector import normalize_event


@click.group()
def main() -> None:
    """Remora - Agent-based code analysis."""


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8420, show_default=True)
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
def serve(host: str, port: int, project_root: str | None, config_path: str | None) -> None:
    """Start the Remora service server."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    root = Path(project_root) if project_root else Path.cwd()
    service = RemoraService.create_default(config=config, project_root=root)
    app = create_app(service)

    import uvicorn

    uvicorn.run(app, host=host, port=port)


@main.command()
@click.argument("target_path")
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
@click.option("--events/--no-events", default=True, show_default=True)
@click.option("--no-wait", is_flag=True, default=False, help="Run immediately without waiting.")
def run(target_path: str, config_path: str | None, events: bool, no_wait: bool) -> None:
    """Run a graph execution for a target path."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    project_root = _resolve_project_root([target_path])
    target_path = _normalize_target_path(target_path, project_root)
    service = RemoraService.create_default(config=config, project_root=project_root)

    async def _run() -> None:
        event_task: asyncio.Task | None = None
        graph_id = uuid.uuid4().hex[:8]
        should_wait = sys.stdin.isatty() and not no_wait

        click.echo(f"Graph ID: {graph_id}")
        if should_wait:
            await _wait_for_gate(graph_id)

        async def _stream_events() -> None:
            async with service.event_bus.stream() as stream:
                async for event in stream:
                    envelope = normalize_event(event)
                    click.echo(json.dumps(envelope, default=str))

        if events:
            event_task = asyncio.create_task(_stream_events())

        response = await service.run(RunRequest(target_path=target_path, graph_id=graph_id))

        async def _wait_for(event_type):
            return await service.event_bus.wait_for(
                event_type,
                lambda event: getattr(event, "graph_id", None) == response.graph_id,
                timeout=config.execution.timeout,
            )

        completed_task = asyncio.create_task(_wait_for(GraphCompleteEvent))
        error_task = asyncio.create_task(_wait_for(GraphErrorEvent))

        try:
            done, pending = await asyncio.wait(
                {completed_task, error_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        finally:
            if event_task:
                event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await event_task

        result = next(iter(done)).result()
        if isinstance(result, GraphErrorEvent):
            raise click.ClickException(result.error)

        click.echo(f"Completed graph {response.graph_id}")

    try:
        asyncio.run(_run())
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise click.ClickException("Graph execution timed out") from exc


def _resolve_project_root(paths: list[str]) -> Path:
    resolved: list[Path] = []
    for path in paths:
        path_obj = Path(path).resolve()
        resolved.append(path_obj.parent if path_obj.is_file() else path_obj)
    if not resolved:
        return Path.cwd()
    if len(resolved) == 1:
        return resolved[0]
    return Path(os.path.commonpath([str(path) for path in resolved]))


def _normalize_target_path(target_path: str, project_root: Path) -> str:
    resolved_target = Path(target_path).resolve()
    try:
        relative = resolved_target.relative_to(project_root)
        return relative.as_posix() or "."
    except ValueError:
        return resolved_target.as_posix()


def _gate_root() -> Path:
    env_path = os.environ.get("REMORA_RUN_GATE_DIR")
    if env_path:
        return Path(env_path)
    return Path.cwd() / ".remora" / "run_gates"


async def _wait_for_gate(graph_id: str) -> None:
    gate_root = _gate_root()
    gate_root.mkdir(parents=True, exist_ok=True)
    gate_path = gate_root / f"{graph_id}.start"

    click.echo("Waiting for playback start.")
    click.echo(f"Press Enter or create: {gate_path}")

    input_task = asyncio.create_task(asyncio.to_thread(sys.stdin.readline))
    try:
        while True:
            if gate_path.exists():
                break
            done, _ = await asyncio.wait(
                {input_task},
                timeout=0.5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if done:
                break
    finally:
        input_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await input_task
    if gate_path.exists():
        with contextlib.suppress(OSError):
            gate_path.unlink()


if __name__ == "__main__":
    main()
