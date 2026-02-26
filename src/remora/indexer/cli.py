"""CLI entry point for the indexer daemon."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from remora.indexer.daemon import IndexerConfig, IndexerDaemon

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

app = typer.Typer(help="Remora Indexer - Background file indexing daemon")


@app.command()
def run(
    watch: bool = typer.Option(
        True,
        "--no-watch",
        help="Run once without watching for changes",
    ),
    paths: list[str] = typer.Option(
        ["src/"],
        "--path",
        "-p",
        help="Paths to watch for changes",
    ),
    store: str = typer.Option(
        ".remora/indexer.db",
        "--store",
        "-s",
        help="Path to indexer store",
    ),
    workers: int = typer.Option(
        8,
        "--workers",
        "-w",
        help="Maximum concurrent workers",
    ),
) -> None:
    """Run the indexer daemon."""
    config = IndexerConfig(
        watch_paths=paths,
        store_path=store,
        max_workers=workers,
    )

    daemon = IndexerDaemon(config)

    try:
        asyncio.run(daemon.start())
    except KeyboardInterrupt:
        logger.info("Indexer stopped by user")


@app.command()
def status(
    store: str = typer.Option(
        ".remora/indexer.db",
        "--store",
        "-s",
        help="Path to indexer store",
    ),
) -> None:
    """Show indexer status."""

    async def get_status():
        from fsdantic import Fsdantic
        from remora.indexer.store import NodeStateStore

        path = Path(store)
        if not path.exists():
            typer.echo(f"Store not found: {store}")
            raise typer.Exit(1)

        workspace = await Fsdantic.open(path=str(path))
        store_instance = NodeStateStore(workspace)

        stats = await store_instance.stats()
        files = await store_instance.list_all_files()

        await workspace.close()

        return stats, files

    stats, files = asyncio.run(get_status())

    typer.echo(f"Indexer Status")
    typer.echo(f"===============")
    typer.echo(f"Indexed files: {stats['files']}")
    typer.echo(f"Indexed nodes: {stats['nodes']}")

    if files:
        typer.echo(f"\nTracked files:")
        for f in files[:10]:
            typer.echo(f"  {f.file_path} ({f.node_count} nodes)")
        if len(files) > 10:
            typer.echo(f"  ... and {len(files) - 10} more")


if __name__ == "__main__":
    app()
