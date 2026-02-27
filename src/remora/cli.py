from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from remora.config import ConfigError, load_config, serialize_config

app = typer.Typer(help="Remora CLI for inspecting configuration")


@app.command()
def config(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        dir_okay=False,
        resolve_path=True,
        help="Path to remora.yaml",
    ),
    output_format: str = typer.Option("yaml", "--format", "-f", help="yaml or json"),
) -> None:
    """Show the active Remora configuration."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"{exc.code}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    payload = serialize_config(cfg)
    normalized = output_format.lower()
    if normalized == "yaml":
        typer.echo(yaml.safe_dump(payload, sort_keys=False))
    elif normalized == "json":
        typer.echo(json.dumps(payload, indent=2))
    else:
        raise typer.BadParameter("format must be 'yaml' or 'json'")
