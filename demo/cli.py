"""CLI entry points for AST Summary demo."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from cairn.runtime.workspace_manager import WorkspaceManager

from demo import engine, events
from demo import parser as ast_parser
from demo.config import DemoConfig, load_demo_config
from demo.models import AstNode
from demo.tui import AstDashboardApp


def _run_summary(filepath: Path, config: DemoConfig) -> None:
    """Parse a file and generate recursive summaries."""
    typer.echo(f"Parsing {filepath}...")

    events.set_event_file(config.event_file)
    events.clear_events()

    root_node, _ = ast_parser.parse_file(filepath)

    all_nodes = root_node.flatten()
    events.emit_event("parsed", "AST", "System", f"Discovered {len(all_nodes)} nodes. Initiating workspaces.")

    config.cache_dir.mkdir(parents=True, exist_ok=True)
    workspace_manager = WorkspaceManager()

    asyncio.run(engine.process_node(root_node, workspace_manager, config.cache_dir, config))

    events.emit_event("complete", "System", "System", "AST Summary Rollup Complete.")
    typer.echo("Done!")

    typer.echo("\n--- Final Aggregated Summaries ---")
    _display_tree(root_node)


def _display_tree(node: AstNode, indent: int = 0) -> None:
    """Print the final tree to stdout."""
    prefix = "  " * indent
    typer.echo(f"{prefix}- {node.node_type}: {node.name}")
    typer.echo(f"{prefix}  Summary: {node.summary}")
    for child in node.children:
        _display_tree(child, indent + 1)


def _launch_ui(event_file: Path) -> None:
    """Launch the Rich dashboard."""
    events.set_event_file(event_file)
    app = AstDashboardApp(event_file)
    app.run()


app = typer.Typer(help="AST Summary Demo - Recursive Documentation & Review")


@app.command()
def run(
    filepath: Path = typer.Argument(..., help="Path to the file to summarize"),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-f",
        help="Path to config file",
    ),
    cache: Path | None = typer.Option(
        None,
        "--cache",
        "-c",
        help="Cache directory for workspaces",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model to use for summarization",
    ),
    base_url: str | None = typer.Option(
        None,
        "--url",
        "-u",
        help="vLLM server base URL",
    ),
) -> None:
    """Parse a file and generate recursive summaries."""
    config = load_demo_config(config_path)

    if cache:
        config.cache_dir = cache
    if model:
        config.model = model
    if base_url:
        config.base_url = base_url

    _run_summary(filepath, config)


@app.command()
def ui(
    event_file: Path = typer.Option(
        Path(".ast_summary_events.jsonl"),
        "--events",
        "-e",
        help="Path to the events JSONL file",
    ),
) -> None:
    """Launch the live dashboard."""
    _launch_ui(event_file)


if __name__ == "__main__":
    app()
