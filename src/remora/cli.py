"""Command-line interface for Remora."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from remora.config import ConfigError, RemoraConfig, load_config, serialize_config

app = typer.Typer(help="Remora CLI.")
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("remora"))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", callback=_version_callback, is_eager=True),
) -> None:
    pass


def _build_overrides(
    discovery_language: str | None,
    query_pack: str | None,
    agents_dir: Path | None,
    max_turns: int | None,
    max_tokens: int | None,
    temperature: float | None,
    tool_choice: str | None,
    cairn_command: str | None,
    cairn_home: Path | None,
    max_concurrent_agents: int | None,
    cairn_timeout: int | None,
    event_stream: bool | None,
    event_stream_file: Path | None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}

    override_mapping: dict[str, tuple[str, ...]] = {
        "discovery_language": ("discovery", "language"),
        "query_pack": ("discovery", "query_pack"),
        "agents_dir": ("agents_dir",),
        "max_turns": ("runner", "max_turns"),
        "max_tokens": ("runner", "max_tokens"),
        "temperature": ("runner", "temperature"),
        "tool_choice": ("runner", "tool_choice"),
        "cairn_command": ("cairn", "command"),
        "cairn_home": ("cairn", "home"),
        "max_concurrent_agents": ("cairn", "max_concurrent_agents"),
        "cairn_timeout": ("cairn", "timeout"),
        "event_stream": ("event_stream", "enabled"),
        "event_stream_file": ("event_stream", "output"),
    }

    values: dict[str, Any] = {
        "discovery_language": discovery_language,
        "query_pack": query_pack,
        "agents_dir": agents_dir,
        "max_turns": max_turns,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "tool_choice": tool_choice,
        "cairn_command": cairn_command,
        "cairn_home": cairn_home,
        "max_concurrent_agents": max_concurrent_agents,
        "cairn_timeout": cairn_timeout,
        "event_stream": event_stream,
        "event_stream_file": event_stream_file,
    }

    for key, path in override_mapping.items():
        value = values.get(key)
        if value is None:
            continue
        target = overrides
        for segment in path[:-1]:
            target = target.setdefault(segment, {})
        target[path[-1]] = value

    return overrides


def _print_config_error(code: str, message: str) -> None:
    typer.echo(f"{code}: {message}", err=True)


@app.command()
def config(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        dir_okay=False,
        resolve_path=True,
    ),
    output_format: str = typer.Option("yaml", "--format", "-f"),
    discovery_language: str | None = typer.Option(None, "--discovery-language"),
    query_pack: str | None = typer.Option(None, "--query-pack"),
    agents_dir: Path | None = typer.Option(None, "--agents-dir"),
    max_turns: int | None = typer.Option(None, "--max-turns"),
    max_tokens: int | None = typer.Option(None, "--max-tokens"),
    temperature: float | None = typer.Option(None, "--temperature"),
    tool_choice: str | None = typer.Option(None, "--tool-choice"),
    cairn_command: str | None = typer.Option(None, "--cairn-command"),
    cairn_home: Path | None = typer.Option(None, "--cairn-home"),
    max_concurrent_agents: int | None = typer.Option(None, "--max-concurrent-agents"),
    cairn_timeout: int | None = typer.Option(None, "--cairn-timeout"),
    event_stream: bool | None = typer.Option(None, "--event-stream/--no-event-stream"),
    event_stream_file: Path | None = typer.Option(
        None,
        "--event-stream-file",
        dir_okay=False,
        resolve_path=True,
    ),
) -> None:
    """Show current configuration."""
    overrides = _build_overrides(
        discovery_language,
        query_pack,
        agents_dir,
        max_turns,
        max_tokens,
        temperature,
        tool_choice,
        cairn_command,
        cairn_home,
        max_concurrent_agents,
        cairn_timeout,
        event_stream,
        event_stream_file,
    )
    try:
        config_data = load_config(config_path, overrides)
    except ConfigError as exc:
        _print_config_error(exc.code, str(exc))
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        _print_config_error(ConfigError.code, str(exc))
        raise typer.Exit(code=1) from exc
    payload = serialize_config(config_data)
    output_format_normalized = output_format.lower()
    if output_format_normalized == "yaml":
        output = yaml.safe_dump(payload, sort_keys=False)
    elif output_format_normalized == "json":
        output = json.dumps(payload, indent=2)
    else:
        raise typer.BadParameter("Format must be 'yaml' or 'json'.")
    typer.echo(output)


def _fetch_models(server_config: Any) -> set[str]:
    """Fetch available models from vLLM server."""
    try:
        import openai
    except (ImportError, RuntimeError):
        return set()

    try:
        client = openai.OpenAI(
            base_url=server_config.base_url,
            api_key=server_config.api_key,
            timeout=5,
        )
        response = client.models.list()
        return {model.id for model in response.data}
    except Exception:
        return set()


@app.command("metrics")
def show_metrics() -> None:
    """Show Hub daemon metrics."""
    from remora.hub.metrics import get_metrics

    metrics = get_metrics()
    data = metrics.to_dict()

    console.print("=== Hub Metrics ===\n")
    console.print("[bold]Counters:[/bold]")
    for key, value in data["counters"].items():
        console.print(f"  {key}: {value}")

    console.print("\n[bold]Timing:[/bold]")
    for key, value in data["timing"].items():
        console.print(f"  {key}: {value}")

    console.print("\n[bold]Gauges:[/bold]")
    for key, value in data["gauges"].items():
        console.print(f"  {key}: {value}")
    console.print()


@app.command("list-agents")
def list_agents(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        dir_okay=False,
        resolve_path=True,
    ),
    output_format: str = typer.Option("table", "--format", "-f"),
) -> None:
    """List available agents and their status."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        _print_config_error(exc.code, str(exc))
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        _print_config_error(ConfigError.code, str(exc))
        raise typer.Exit(code=1) from exc

    # Fetch available models
    available_models = _fetch_models(config.server)
    server_reachable = bool(available_models)

    # Build agent info from config.operations
    agents = []
    for op_name, op_config in config.operations.items():
        yaml_path = config.agents_dir / op_config.subagent
        yaml_exists = yaml_path.exists()

        # Check model availability
        adapter = op_config.model_id or config.server.default_adapter
        model_available = adapter in available_models

        agents.append(
            {
                "name": op_name,
                "enabled": op_config.enabled,
                "yaml_path": str(yaml_path),
                "yaml_exists": yaml_exists,
                "adapter": adapter,
                "model_available": model_available,
            }
        )

    # Output
    if output_format.lower() == "json":
        typer.echo(json.dumps(agents, indent=2))
    else:
        # Table format
        if not server_reachable:
            console.print("[yellow]Warning: vLLM server not reachable[/yellow]\n")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Agent", style="cyan")
        table.add_column("Enabled", justify="center")
        table.add_column("YAML", justify="center")
        table.add_column("Adapter")
        table.add_column("Model", justify="center")

        for agent in agents:
            enabled_icon = "[green]✓[/green]" if agent["enabled"] else "[dim]-[/dim]"
            yaml_icon = "[green]✓[/green]" if agent["yaml_exists"] else "[red]✗[/red]"

            if not server_reachable:
                model_icon = "[dim]?[/dim]"
            elif agent["model_available"]:
                model_icon = "[green]✓[/green]"
            else:
                model_icon = "[red]✗[/red]"

            table.add_row(
                agent["name"],
                enabled_icon,
                yaml_icon,
                agent["adapter"],
                model_icon,
            )

        console.print(table)
        console.print("\nLegend: ✓ = OK, ✗ = Missing/Error, ? = Unknown, - = N/A")
        table.add_column("Model", justify="center")

        for agent in agents:
            enabled_icon = "[green]✓[/green]" if agent["enabled"] else "[dim]-[/dim]"
            yaml_icon = "[green]✓[/green]" if agent["yaml_exists"] else "[red]✗[/red]"

            if not agent["yaml_exists"]:
                grail_icon = "[dim]-[/dim]"
            elif agent["grail_valid"] and agent["grail_warnings"] == 0:
                grail_icon = "[green]✓[/green]"
            elif agent["grail_valid"]:
                grail_icon = f"[yellow]~{agent['grail_warnings']}[/yellow]"
            else:
                grail_icon = "[red]✗[/red]"

            if not server_reachable:
                model_icon = "[dim]?[/dim]"
            elif agent["model_available"]:
                model_icon = "[green]✓[/green]"
            else:
                model_icon = "[red]✗[/red]"

            table.add_row(
                agent["name"],
                enabled_icon,
                yaml_icon,
                grail_icon,
                agent["adapter"],
                model_icon,
            )

        console.print(table)
        console.print("\nLegend: ✓ = OK, ✗ = Missing/Error, ~N = Warnings, ? = Unknown, - = N/A")
