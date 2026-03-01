"""Remora CLI entry points."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import click

from remora.adapters.starlette import create_app
from remora.core.config import ConfigError, load_config
from remora.service.api import RemoraService


@click.group()
def main() -> None:
    """Remora - Agent-based code analysis."""


@main.group()
def swarm() -> None:
    """Swarm commands for reactive agent management."""
    pass


@swarm.command("start")
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
@click.option("--nvim", is_flag=True, help="Start JSON-RPC NvimServer")
@click.option(
    "--lsp",
    is_flag=True,
    help="Start LSP server for Neovim integration",
)
def swarm_start(
    project_root: str | None,
    config_path: str | None,
    nvim: bool,
    lsp: bool,
) -> None:
    """Start the reactive swarm (reconciler + runner)."""
    if lsp:
        from remora.lsp.__main__ import main as lsp_main

        lsp_main()
        return

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    root = Path(project_root) if project_root else Path.cwd()

    async def _start() -> None:
        from remora.core.event_bus import EventBus
        from remora.core.event_store import EventStore
        from remora.core.swarm_state import SwarmState
        from remora.core.subscriptions import SubscriptionRegistry
        from remora.core.reconciler import reconcile_on_startup
        from remora.core.agent_runner import AgentRunner

        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"
        subscriptions_path = swarm_path / "subscriptions.db"
        swarm_state_path = swarm_path / "swarm_state.db"

        event_bus = EventBus()
        subscriptions = SubscriptionRegistry(subscriptions_path)
        swarm_state = SwarmState(swarm_state_path)
        event_store = EventStore(
            event_store_path,
            subscriptions=subscriptions,
            event_bus=event_bus,
        )

        await event_store.initialize()
        await subscriptions.initialize()
        await swarm_state.initialize()

        event_store.set_subscriptions(subscriptions)
        event_store.set_event_bus(event_bus)

        click.echo("Reconciling swarm...")
        swarm_id = getattr(config, "swarm_id", "swarm") if hasattr(config, "__dataclass_fields__") else "swarm"
        result = await reconcile_on_startup(
            root,
            swarm_state,
            subscriptions,
            event_store=event_store,
            swarm_id=swarm_id,
        )
        click.echo(f"Swarm reconciled: {result['created']} new, {result['orphaned']} orphaned, {result['total']} total")

        runner = AgentRunner(
            event_store=event_store,
            subscriptions=subscriptions,
            swarm_state=swarm_state,
            config=config,
            event_bus=event_bus,
            project_root=root,
        )
        runner_task = asyncio.create_task(runner.run_forever())

        nvim_server = None
        if nvim:
            from remora.nvim.server import NvimServer

            nvim_socket = swarm_path / "nvim.sock"
            nvim_server = NvimServer(
                nvim_socket,
                event_store=event_store,
                subscriptions=subscriptions,
                event_bus=event_bus,
                project_root=root,
                swarm_id=swarm_id,
            )
            await nvim_server.start()
            click.echo(f"Neovim server started on {nvim_socket}")

        click.echo("Swarm started. Press Ctrl+C to stop.")

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner_task
            await runner.stop()
            if nvim_server:
                await nvim_server.stop()
            await swarm_state.close()

    asyncio.run(_start())


@swarm.command("reconcile")
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
def swarm_reconcile(project_root: str | None, config_path: str | None) -> None:
    """Run swarm reconciliation only."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    root = Path(project_root) if project_root else Path.cwd()

    async def _reconcile() -> None:
        from remora.core.swarm_state import SwarmState
        from remora.core.subscriptions import SubscriptionRegistry
        from remora.core.reconciler import reconcile_on_startup

        swarm_path = root / ".remora"
        subscriptions_path = swarm_path / "subscriptions.db"
        swarm_state_path = swarm_path / "swarm_state.db"

        subscriptions = SubscriptionRegistry(subscriptions_path)
        swarm_state = SwarmState(swarm_state_path)

        await subscriptions.initialize()
        await swarm_state.initialize()

        result = await reconcile_on_startup(
            root,
            swarm_state,
            subscriptions,
        )
        click.echo(f"Reconciliation complete:")
        click.echo(f"  Created: {result['created']}")
        click.echo(f"  Orphaned: {result['orphaned']}")
        click.echo(f"  Total: {result['total']}")

        await subscriptions.close()
        await swarm_state.close()

    asyncio.run(_reconcile())


@swarm.command("list")
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
def swarm_list(project_root: str | None) -> None:
    """List known agents in the swarm."""
    root = Path(project_root) if project_root else Path.cwd()

    swarm_path = root / ".remora"
    swarm_state_path = swarm_path / "swarm_state.db"

    if not swarm_state_path.exists():
        click.echo("No swarm state found. Run 'remora swarm reconcile' first.")
        return

    from remora.core.swarm_state import SwarmState

    async def _list() -> None:
        swarm_state = SwarmState(swarm_state_path)
        await swarm_state.initialize()

        agents = await swarm_state.list_agents()

        if not agents:
            click.echo("No agents found.")
        else:
            click.echo(f"Agents ({len(agents)}):")
            for agent in agents:
                click.echo(f"  {agent.agent_id[:16]}... | {agent.node_type} | {agent.file_path} | {agent.status}")

        await swarm_state.close()

    asyncio.run(_list())


@swarm.command("emit")
@click.argument("event_type")
@click.argument("data", required=False)
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
def swarm_emit(event_type: str, data: str | None, project_root: str | None) -> None:
    """Emit an event to the swarm."""
    root = Path(project_root) if project_root else Path.cwd()

    import json

    event_data = {}
    if data:
        try:
            event_data = json.loads(data)
        except json.JSONDecodeError:
            raise click.ClickException("Data must be valid JSON")

    async def _emit() -> None:
        from remora.core.event_store import EventStore
        from remora.core.events import AgentMessageEvent, ContentChangedEvent

        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"

        event_store = EventStore(event_store_path)
        await event_store.initialize()

        if event_type == "AgentMessageEvent":
            event = AgentMessageEvent(
                from_agent=event_data.get("from_agent", "cli"),
                to_agent=event_data.get("to_agent", ""),
                content=event_data.get("content", ""),
                tags=event_data.get("tags", []),
            )
        elif event_type == "ContentChangedEvent":
            event = ContentChangedEvent(
                path=event_data.get("path", ""),
                diff=event_data.get("diff"),
            )
        else:
            raise click.ClickException(f"Unknown event type: {event_type}")

        event_id = await event_store.append("cli", event)
        click.echo(f"Event emitted: {event_type} (id: {event_id})")

        await event_store.close()

    asyncio.run(_emit())


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


if __name__ == "__main__":
    main()
