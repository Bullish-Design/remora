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

from remora.config import ConfigError, load_config, serialize_config
from remora.errors import CONFIG_003

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


def _not_implemented() -> None:
    console.print("Not yet implemented")


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


@app.command()
def analyze() -> None:
    _not_implemented()


@app.command()
def watch() -> None:
    _not_implemented()


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


@app.command("list-agents")
def list_agents() -> None:
    _not_implemented()
