"""Command-line interface for Remora."""

from __future__ import annotations

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


def _not_implemented() -> None:
    console.print("Not yet implemented")


def _build_overrides(
    root_dirs: list[Path] | None,
    queries: list[str] | None,
    agents_dir: Path | None,
    max_turns: int | None,
    max_concurrent_runners: int | None,
    runner_timeout: int | None,
    cairn_timeout: int | None,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if root_dirs is not None:
        overrides["root_dirs"] = root_dirs
    if queries is not None:
        overrides["queries"] = queries
    if agents_dir is not None:
        overrides["agents_dir"] = agents_dir
    runner_overrides: dict[str, Any] = {}
    if max_turns is not None:
        runner_overrides["max_turns"] = max_turns
    if max_concurrent_runners is not None:
        runner_overrides["max_concurrent_runners"] = max_concurrent_runners
    if runner_timeout is not None:
        runner_overrides["timeout"] = runner_timeout
    if runner_overrides:
        overrides["runner"] = runner_overrides
    if cairn_timeout is not None:
        overrides["cairn"] = {"timeout": cairn_timeout}
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
    root_dirs: list[Path] | None = typer.Option(None, "--root-dir"),
    queries: list[str] | None = typer.Option(None, "--query"),
    agents_dir: Path | None = typer.Option(None, "--agents-dir"),
    max_turns: int | None = typer.Option(None, "--max-turns"),
    max_concurrent_runners: int | None = typer.Option(None, "--max-concurrent-runners"),
    runner_timeout: int | None = typer.Option(None, "--runner-timeout"),
    cairn_timeout: int | None = typer.Option(None, "--cairn-timeout"),
) -> None:
    overrides = _build_overrides(
        root_dirs,
        queries,
        agents_dir,
        max_turns,
        max_concurrent_runners,
        runner_timeout,
        cairn_timeout,
    )
    try:
        config_data = load_config(config_path, overrides)
    except ConfigError as exc:
        _print_config_error(exc.code, str(exc))
        raise typer.Exit(code=3) from exc
    except ValidationError as exc:
        _print_config_error(CONFIG_003, str(exc))
        raise typer.Exit(code=3) from exc
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
