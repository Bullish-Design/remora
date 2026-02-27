"""Remora CLI entry points."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from remora.adapters.starlette import create_app
from remora.core.config import ConfigError, load_config
from remora.core.container import RemoraContainer
from remora.core.events import GraphCompleteEvent, GraphErrorEvent
from remora.models import RunRequest
from remora.service.api import RemoraService


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
    container = RemoraContainer.create(config=config, project_root=root)
    service = RemoraService(container=container)
    app = create_app(service)

    import uvicorn

    uvicorn.run(app, host=host, port=port)


@main.command()
@click.argument("target_path")
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
def run(target_path: str, config_path: str | None) -> None:
    """Run a graph execution for a target path."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    project_root = _resolve_project_root([target_path])
    container = RemoraContainer.create(config=config, project_root=project_root)
    service = RemoraService(container=container)

    async def _run() -> None:
        response = await service.run(RunRequest(target_path=target_path))

        async def _wait_for(event_type):
            return await service.event_bus.wait_for(
                event_type,
                lambda event: getattr(event, "graph_id", None) == response.graph_id,
                timeout=config.execution.timeout,
            )

        completed_task = asyncio.create_task(_wait_for(GraphCompleteEvent))
        error_task = asyncio.create_task(_wait_for(GraphErrorEvent))

        done, pending = await asyncio.wait(
            {completed_task, error_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

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


if __name__ == "__main__":
    main()
