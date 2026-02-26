"""Dashboard CLI entry point."""

import logging
from pathlib import Path

import typer

from remora.config import load_config
from remora.dashboard.app import create_app

app = typer.Typer(help="Remora Dashboard - Web UI for agent execution monitoring")

logger = logging.getLogger(__name__)


@app.command()
def run(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8420, help="Port to bind to"),
    debug: bool = typer.Option(False, help="Enable debug mode"),
    config_path: Path = typer.Option(
        Path("remora.yaml"),
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to remora.yaml config file",
    ),
):
    """Run the dashboard web server."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        config = load_config(config_path)
    except Exception:
        config = None

    dashboard_config = {}
    if config:
        dashboard_config = getattr(config, "dashboard", {})

    import uvicorn

    starlette_app = create_app({**dashboard_config, "debug": debug})

    logger.info(f"Starting Remora Dashboard at http://{host}:{port}")
    uvicorn.run(starlette_app, host=host, port=port)


if __name__ == "__main__":
    app()
