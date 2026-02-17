"""Command-line interface for Remora."""

import typer
from rich.console import Console

app = typer.Typer(help="Remora CLI.")
console = Console()


def _not_implemented() -> None:
    console.print("Not yet implemented")


@app.command()
def analyze() -> None:
    _not_implemented()


@app.command()
def watch() -> None:
    _not_implemented()


@app.command()
def config() -> None:
    _not_implemented()


@app.command("list-agents")
def list_agents() -> None:
    _not_implemented()
