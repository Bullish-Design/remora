"""Remora CLI entry points."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import click

from remora.adapters.starlette import create_app
from remora.core.config import ConfigError, load_config
from remora.service.api import RemoraService
from remora.cli.workspace import workspace


@click.group()
def main() -> None:
    """Remora - Agent-based code analysis."""


# Register workspace command group
main.add_command(workspace)


@main.group()
def swarm() -> None:
    """Swarm commands for reactive agent management."""
    pass


@swarm.command("start")
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
@click.option(
    "--lsp",
    is_flag=True,
    help="Start LSP server for Neovim integration",
)
def swarm_start(
    project_root: str | None,
    config_path: str | None,
    lsp: bool,
) -> None:
    """Start the reactive swarm (reconciler + runner)."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    if lsp:

        async def _prepare_lsp():
            from remora.core.events.event_bus import EventBus
            from remora.core.store.event_store import EventStore
            from remora.core.code.projections import NodeProjection
            from remora.core.code.reconciler import reconcile_on_startup
            from remora.core.events.subscriptions import SubscriptionRegistry

            root = Path(project_root) if project_root else Path.cwd()
            swarm_path = root / ".remora"
            event_store_path = swarm_path / "events" / "events.db"
            subscriptions_path = swarm_path / "subscriptions.db"

            event_bus = EventBus()
            subscriptions = SubscriptionRegistry(subscriptions_path)
            from remora.extensions import extension_matches, load_extensions
            extensions = load_extensions(swarm_path / "models")
            projection = NodeProjection(
                extension_matcher=extension_matches,
                extension_configs=extensions,
            )
            event_store = EventStore(
                event_store_path,
                subscriptions=subscriptions,
                event_bus=event_bus,
                projection=projection,
            )

            await event_store.initialize()
            await subscriptions.initialize()

            event_store.set_subscriptions(subscriptions)
            event_store.set_event_bus(event_bus)

            click.echo("Reconciling swarm...")
            swarm_id = getattr(config, "swarm_id", "swarm") if hasattr(config, "__dataclass_fields__") else "swarm"
            result = await reconcile_on_startup(
                root,
                subscriptions,
                event_store=event_store,
                swarm_id=swarm_id,
            )
            click.echo(
                f"Swarm reconciled: {result['created']} new, {result['orphaned']} orphaned, {result['total']} total"
            )

            return event_store, subscriptions

        event_store, subscriptions = asyncio.run(_prepare_lsp())

        from remora.lsp.__main__ import main as lsp_main

        lsp_main(
            event_store=event_store,
            subscriptions=subscriptions,
        )
        return

    root = Path(project_root) if project_root else Path.cwd()

    async def _start() -> None:
        from remora.core.events.event_bus import EventBus
        from remora.core.store.event_store import EventStore
        from remora.core.code.projections import NodeProjection
        from remora.core.events.subscriptions import SubscriptionRegistry
        from remora.core.code.reconciler import reconcile_on_startup
        from remora.runner.agent_runner import AgentRunner

        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"
        subscriptions_path = swarm_path / "subscriptions.db"

        event_bus = EventBus()
        subscriptions = SubscriptionRegistry(subscriptions_path)
        from remora.extensions import extension_matches, load_extensions
        extensions = load_extensions(swarm_path / "models")
        projection = NodeProjection(
            extension_matcher=extension_matches,
            extension_configs=extensions,
        )
        event_store = EventStore(
            event_store_path,
            subscriptions=subscriptions,
            event_bus=event_bus,
            projection=projection,
        )

        await event_store.initialize()
        await subscriptions.initialize()

        event_store.set_subscriptions(subscriptions)
        event_store.set_event_bus(event_bus)

        click.echo("Reconciling swarm...")
        swarm_id = getattr(config, "swarm_id", "swarm") if hasattr(config, "__dataclass_fields__") else "swarm"
        result = await reconcile_on_startup(
            root,
            subscriptions,
            event_store=event_store,
            swarm_id=swarm_id,
        )
        click.echo(f"Swarm reconciled: {result['created']} new, {result['orphaned']} orphaned, {result['total']} total")

        runner = AgentRunner.create_headless(
            event_store=event_store,
            max_trigger_depth=getattr(config, "max_trigger_depth", None),
            trigger_cooldown_ms=getattr(config, "trigger_cooldown_ms", None),
            max_concurrency=getattr(config, "max_concurrency", 4),
        )
        runner._running = True
        runner_task = asyncio.create_task(runner.run_forever())
        bridge_task = asyncio.create_task(runner.run_from_event_store(event_store))

        click.echo("Swarm started. Press Ctrl+C to stop.")

        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            runner.stop()
            runner_task.cancel()
            bridge_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner_task
            with contextlib.suppress(asyncio.CancelledError):
                await bridge_task

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
        from remora.core.events.subscriptions import SubscriptionRegistry
        from remora.core.code.reconciler import reconcile_on_startup
        from remora.core.store.event_store import EventStore
        from remora.core.code.projections import NodeProjection

        swarm_path = root / ".remora"
        subscriptions_path = swarm_path / "subscriptions.db"
        event_store_path = swarm_path / "events" / "events.db"

        subscriptions = SubscriptionRegistry(subscriptions_path)
        from remora.extensions import extension_matches, load_extensions
        extensions = load_extensions(swarm_path / "models")
        projection = NodeProjection(
            extension_matcher=extension_matches,
            extension_configs=extensions,
        )
        event_store = EventStore(
            event_store_path,
            subscriptions=subscriptions,
            projection=projection,
        )

        await subscriptions.initialize()
        await event_store.initialize()

        result = await reconcile_on_startup(
            root,
            subscriptions,
            event_store=event_store,
        )
        click.echo(f"Reconciliation complete:")
        click.echo(f"  Created: {result['created']}")
        click.echo(f"  Orphaned: {result['orphaned']}")
        click.echo(f"  Total: {result['total']}")

        await event_store.close()
        await subscriptions.close()

    asyncio.run(_reconcile())


@swarm.command("list")
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
def swarm_list(project_root: str | None) -> None:
    """List known agents in the swarm."""
    root = Path(project_root) if project_root else Path.cwd()

    swarm_path = root / ".remora"
    event_store_path = swarm_path / "events" / "events.db"

    if not event_store_path.exists():
        click.echo("No event store found. Run 'remora swarm reconcile' first.")
        return

    from remora.core.store.event_store import EventStore

    async def _list() -> None:
        event_store = EventStore(event_store_path)
        await event_store.initialize()

        agents = await event_store.nodes.list_nodes()

        if not agents:
            click.echo("No agents found.")
        else:
            click.echo(f"Agents ({len(agents)}):")
            for agent in agents:
                click.echo(f"  {agent.node_id[:16]}... | {agent.node_type} | {agent.file_path} | {agent.status}")

        await event_store.close()

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
        from remora.core.store.event_store import EventStore
        from remora.core.events.interaction_events import AgentMessageEvent, ContentChangedEvent

        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"

        event_store = EventStore(event_store_path)
        await event_store.initialize()

        if event_type == "AgentMessageEvent":
            event = AgentMessageEvent(
                from_agent=event_data.get("from_agent", "cli"),
                to_agent=event_data.get("to_agent", ""),
                content=event_data.get("content", ""),
                tags=tuple(event_data.get("tags", ())),
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
