"""CLI entry point for the Hub daemon.

Usage:
    remora-hub start [--project-root PATH]
    remora-hub status
    remora-hub stop
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import click

from remora.constants import HUB_DB_NAME
from remora.hub.daemon import HubDaemon


@click.group()
def cli() -> None:
    """Remora Hub daemon management."""


@cli.command()
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Project root directory to watch",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to {HUB_DB_NAME} (default: {{project-root}}/.remora/{HUB_DB_NAME})",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Logging level",
)
@click.option(
    "--foreground/--background",
    default=True,
    help="Run in foreground (default) or background",
)
def start(
    project_root: Path,
    db_path: Path | None,
    log_level: str,
    foreground: bool,
) -> None:
    """Start the Hub daemon."""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not foreground:
        _daemonize()

    daemon = HubDaemon(
        project_root=project_root,
        db_path=db_path,
    )

    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass


@cli.command()
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Project root directory",
)
def status(project_root: Path) -> None:
    """Check Hub daemon status."""
    from fsdantic import Fsdantic

    from remora.hub.store import NodeStateStore

    hub_path = project_root / ".remora" / HUB_DB_NAME
    pid_file = project_root / ".remora" / "hub.pid"

    if not hub_path.exists():
        click.echo("Hub: not initialized")
        click.echo("  Run 'remora-hub start' to initialize")
        return

    daemon_running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            daemon_running = True
        except (ValueError, OSError):
            pass

    async def get_stats():
        workspace = await Fsdantic.open(path=str(hub_path))
        store = NodeStateStore(workspace)
        stats = await store.stats()
        status_obj = await store.get_status()
        await workspace.close()
        return stats, status_obj

    stats, status_obj = asyncio.run(get_stats())

    click.echo(f"Hub: {'running' if daemon_running else 'stopped'}")
    click.echo(f"  Database: {hub_path}")
    click.echo(f"  Files indexed: {stats['files']}")
    click.echo(f"  Nodes indexed: {stats['nodes']}")
    if status_obj and status_obj.last_update:
        last_update = status_obj.last_update
        if isinstance(last_update, str):
            click.echo(f"  Last update: {last_update}")
        else:
            click.echo(f"  Last update: {last_update.isoformat()}")


@cli.command()
@click.option(
    "--project-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path.cwd(),
    help="Project root directory",
)
def stop(project_root: Path) -> None:
    """Stop the Hub daemon."""
    pid_file = project_root / ".remora" / "hub.pid"

    if not pid_file.exists():
        click.echo("Hub daemon not running")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to Hub daemon (PID {pid})")
    except ValueError:
        click.echo("Invalid PID file")
    except OSError as exc:
        click.echo(f"Failed to stop daemon: {exc}")


def _daemonize() -> None:
    """Daemonize the process (Unix only)."""
    if os.name != "posix":
        raise click.ClickException("Background mode only supported on Unix")

    if os.fork() > 0:
        sys.exit(0)

    os.setsid()

    if os.fork() > 0:
        sys.exit(0)

    sys.stdin = open(os.devnull, "r")
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")


def main() -> None:
    """Entry point for remora-hub command."""
    cli()


@cli.command()
@click.option("--workspace", type=click.Path(path_type=Path), default=".remora/hub")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
def serve(workspace: Path, host: str, port: int):
    """Start the Remora Hub server."""
    from remora.hub.server import run_hub

    logging.basicConfig(level=logging.INFO)
    import asyncio

    asyncio.run(run_hub(workspace, host, port))


if __name__ == "__main__":
    main()
