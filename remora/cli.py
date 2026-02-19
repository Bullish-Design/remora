"""Command-line interface for Remora."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from remora.analyzer import RemoraAnalyzer, ResultPresenter
from remora.cairn import CairnCLIClient
from remora.config import ConfigError, RemoraConfig, load_config, serialize_config
from remora.errors import CONFIG_003
from remora.subagent import load_subagent_definition

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
    discovery_overrides: dict[str, Any] = {}
    if discovery_language is not None:
        discovery_overrides["language"] = discovery_language
    if query_pack is not None:
        discovery_overrides["query_pack"] = query_pack
    if discovery_overrides:
        overrides["discovery"] = discovery_overrides
    if agents_dir is not None:
        overrides["agents_dir"] = agents_dir
    runner_overrides: dict[str, Any] = {}
    if max_turns is not None:
        runner_overrides["max_turns"] = max_turns
    if max_tokens is not None:
        runner_overrides["max_tokens"] = max_tokens
    if temperature is not None:
        runner_overrides["temperature"] = temperature
    if tool_choice is not None:
        runner_overrides["tool_choice"] = tool_choice
    if runner_overrides:
        overrides["runner"] = runner_overrides
    cairn_overrides: dict[str, Any] = {}
    if cairn_command is not None:
        cairn_overrides["command"] = cairn_command
    if cairn_home is not None:
        cairn_overrides["home"] = cairn_home
    if max_concurrent_agents is not None:
        cairn_overrides["max_concurrent_agents"] = max_concurrent_agents
    if cairn_timeout is not None:
        cairn_overrides["timeout"] = cairn_timeout
    if cairn_overrides:
        overrides["cairn"] = cairn_overrides
    event_overrides: dict[str, Any] = {}
    if event_stream is not None:
        event_overrides["enabled"] = event_stream
    if event_stream_file is not None:
        event_overrides["output"] = event_stream_file
    if event_overrides:
        overrides["event_stream"] = event_overrides
    return overrides


def _print_config_error(code: str, message: str) -> None:
    typer.echo(f"{code}: {message}", err=True)


def _exit_code(results: Any) -> int:
    """Determine exit code based on results."""
    if results is None:
        return 2
    if results.failed_operations == 0:
        return 0
    if results.successful_operations == 0:
        return 2
    return 1


@app.command()
def analyze(
    paths: list[Path] = typer.Argument(
        default_factory=lambda: [Path(".")],
        help="Files or directories to analyze",
    ),
    operations: str = typer.Option(
        "lint,test,docstring",
        "--operations",
        "-o",
        help="Comma-separated list of operations to run",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table, json, interactive",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        dir_okay=False,
        resolve_path=True,
    ),
    auto_accept: bool = typer.Option(
        False,
        "--auto-accept",
        help="Auto-accept all successful results",
    ),
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
    """Analyze Python code and generate suggestions."""
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
        config = load_config(config_path, overrides)
    except ConfigError as exc:
        _print_config_error(exc.code, str(exc))
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        _print_config_error(CONFIG_003, str(exc))
        raise typer.Exit(code=1) from exc

    # Parse operations
    ops = [op.strip() for op in operations.split(",") if op.strip()]

    # Create analyzer and run
    async def _run():
        cairn_client = CairnCLIClient(config.cairn)
        analyzer = RemoraAnalyzer(config, cairn_client)
        results = await analyzer.analyze(paths, ops)

        # Display results
        presenter = ResultPresenter(output_format)
        presenter.display(results)

        # Auto-accept or interactive review
        if auto_accept:
            await analyzer.bulk_accept()
            console.print("\n[green]✓ All successful changes accepted[/green]")
        elif output_format == "interactive":
            await presenter.interactive_review(analyzer, results)

        return results

    results = asyncio.run(_run())
    raise typer.Exit(_exit_code(results))


@app.command()
def watch(
    paths: list[Path] = typer.Argument(
        default_factory=lambda: [Path(".")],
        help="Directories to watch",
    ),
    operations: str = typer.Option(
        "lint,test,docstring",
        "--operations",
        "-o",
        help="Comma-separated list of operations to run",
    ),
    debounce_ms: int = typer.Option(
        500,
        "--debounce",
        help="Debounce delay in milliseconds",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        dir_okay=False,
        resolve_path=True,
    ),
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
    """Watch files and re-analyze on changes."""
    from remora.orchestrator import Coordinator
    from remora.watcher import RemoraFileWatcher

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
        config = load_config(config_path, overrides)
    except ConfigError as exc:
        _print_config_error(exc.code, str(exc))
        raise typer.Exit(code=1) from exc
    except ValidationError as exc:
        _print_config_error(CONFIG_003, str(exc))
        raise typer.Exit(code=1) from exc

    # Parse operations
    ops = [op.strip() for op in operations.split(",") if op.strip()]

    # CLI --debounce overrides config value
    effective_debounce = debounce_ms

    console.print(f"[bold]Watching {len(paths)} path(s) for changes...[/bold]")
    console.print(f"Operations: {', '.join(ops)}")
    console.print(f"Extensions: {', '.join(sorted(config.watch.extensions))}")
    console.print(f"Debounce: {effective_debounce}ms")
    console.print("Press Ctrl+C to stop\n")

    try:

        async def _watch() -> None:
            cairn_client = CairnCLIClient(config.cairn)
            async with Coordinator(
                config,
                cairn_client,
                event_stream_enabled=event_stream,
                event_stream_output=event_stream_file,
            ) as coordinator:

                async def on_changes(changes: list) -> None:
                    changed_paths = [c.path for c in changes]
                    console.print(
                        f"\n[bold cyan]Detected {len(changes)} change(s), "
                        f"re-analyzing...[/bold cyan]"
                    )
                    analyzer = RemoraAnalyzer(config, cairn_client)
                    results = await analyzer.analyze(changed_paths, ops)
                    presenter = ResultPresenter("table")
                    presenter.display(results)

                watcher = RemoraFileWatcher(
                    watch_paths=[p.resolve() for p in paths],
                    on_changes=on_changes,
                    extensions=config.watch.extensions,
                    ignore_patterns=config.watch.ignore_patterns,
                    debounce_ms=effective_debounce,
                )

                await watcher.start()

        asyncio.run(_watch())
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped[/yellow]")


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
        _print_config_error(CONFIG_003, str(exc))
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

        client = openai.OpenAI(
            base_url=server_config.base_url,
            api_key=server_config.api_key,
            timeout=5,
        )
        response = client.models.list()
        return {model.id for model in response.data}
    except Exception:
        return set()


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
        _print_config_error(CONFIG_003, str(exc))
        raise typer.Exit(code=1) from exc

    # Fetch available models
    available_models = _fetch_models(config.server)
    server_reachable = bool(available_models)

    # Build agent info
    agents = []
    for op_name, op_config in config.operations.items():
        yaml_path = config.agents_dir / op_config.subagent

        # Check YAML exists
        yaml_exists = yaml_path.exists()

        # Check Grail validation if YAML exists
        grail_valid = False
        grail_warnings = []
        if yaml_exists:
            try:
                definition = load_subagent_definition(yaml_path, config.agents_dir)
                grail_summary = definition.grail_summary
                grail_valid = grail_summary.get("valid", False)
                grail_warnings = grail_summary.get("warnings", [])
            except Exception:
                pass

        # Check model availability
        adapter = op_config.model_id or config.server.default_adapter
        model_available = adapter in available_models

        agents.append(
            {
                "name": op_name,
                "enabled": op_config.enabled,
                "yaml_path": str(yaml_path),
                "yaml_exists": yaml_exists,
                "grail_valid": grail_valid,
                "grail_warnings": len(grail_warnings),
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
        table.add_column("Grail", justify="center")
        table.add_column("Adapter")
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
