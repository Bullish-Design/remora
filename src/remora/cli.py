"""Remora CLI entry points."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from remora.config import load_config
from remora.dashboard.app import create_app
from remora.discovery import discover
from remora.event_bus import EventBus
from remora.executor import GraphExecutor, ResultSummary
from remora.graph import build_graph
from remora.indexer.daemon import IndexerConfig as DaemonIndexerConfig, IndexerDaemon


@click.group()
def main() -> None:
    """Remora - Agent-based code analysis."""
    pass


@main.command()
@click.argument("paths", nargs=-1)
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True), help="Config file path")
def run(paths: tuple[str, ...], config_path: str | None) -> None:
    """Run agent graph on specified paths."""
    cfg = load_config(config_path)

    discovery_paths = list(paths) or list(cfg.discovery.paths)
    nodes = discover(
        discovery_paths,
        languages=list(cfg.discovery.languages) if cfg.discovery.languages else None,
        max_workers=cfg.discovery.max_workers,
    )

    bundle_root = Path(cfg.bundles.path)
    bundle_mapping = {
        node_type: bundle_root / bundle
        for node_type, bundle in cfg.bundles.mapping.items()
    }

    if not bundle_mapping:
        raise click.UsageError("No bundle mapping configured")

    graph = build_graph(nodes, bundle_mapping)

    event_bus = EventBus()
    executor = GraphExecutor(cfg, event_bus)

    async def run_async() -> dict[str, ResultSummary]:
        return await executor.run(graph, "cli-run")

    results = asyncio.run(run_async())
    click.echo(f"Completed {len(results)} agents")


@main.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8420)
def dashboard(host: str, port: int) -> None:
    """Start the dashboard server."""

    async def serve() -> None:
        app = await create_app()
        import uvicorn

        uvicorn.run(app, host=host, port=port)

    asyncio.run(serve())


@main.command()
@click.argument("paths", nargs=-1)
def index(paths: tuple[str, ...]) -> None:
    """Start the indexer daemon."""
    cfg = load_config()
    daemon_cfg = DaemonIndexerConfig(
        watch_paths=list(paths) or list(cfg.indexer.watch_paths),
        store_path=cfg.indexer.store_path,
    )

    daemon = IndexerDaemon(daemon_cfg)
    asyncio.run(daemon.start())


if __name__ == "__main__":
    main()
