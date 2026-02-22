"""Run a small Remora demo workload for the dashboard."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer


from remora.config import OperationConfig, RemoraConfig, load_config
from remora.discovery import CSTNode, TreeSitterDiscoverer
from remora.orchestrator import Coordinator

app = typer.Typer(help="Run a small Remora demo workload.")


def _demo_root() -> Path:
    return Path(__file__).resolve().parents[1] / "training" / "demo_project"


def _build_demo_config(base: RemoraConfig, demo_root: Path) -> RemoraConfig:
    lint_op = base.operations.get("lint", OperationConfig(subagent="lint"))
    docstring_op = base.operations.get(
        "docstring",
        OperationConfig.model_validate({"subagent": "docstring", "style": "google"}),
    )
    type_check_op = lint_op.model_copy()
    operations = {
        "lint": lint_op,
        "docstring": docstring_op,
        "type_check": type_check_op,
    }
    return base.model_copy(
        update={
            "operations": operations,
        }
    )


def _collect_nodes(config: RemoraConfig, demo_root: Path, event_emitter=None) -> list[CSTNode]:
    discoverer = TreeSitterDiscoverer(
        root_dirs=[demo_root],
        language=config.discovery.language,
        query_pack=config.discovery.query_pack,
        query_dir=config.discovery.query_dir,
        event_emitter=event_emitter,
    )
    return discoverer.discover()


async def _run_once(config: RemoraConfig, demo_root: Path) -> None:
    async with Coordinator(
        config=config,
        event_stream_enabled=True,
    ) as coordinator:
        nodes = _collect_nodes(config, demo_root, event_emitter=coordinator._event_emitter)
        operations = list(config.operations.keys())

        for node in nodes:
            await coordinator.process_node(node, operations)


@app.command()
def main(
    continuous: bool = typer.Option(False, "--continuous", "-c"),
    sleep_seconds: float = typer.Option(2.0, "--sleep"),
) -> None:
    demo_root = _demo_root()
    base_config = load_config(None, overrides=None)
    config = _build_demo_config(base_config, demo_root)

    async def _runner() -> None:
        if not continuous:
            await _run_once(config, demo_root)
            return
        while True:
            await _run_once(config, demo_root)
            await asyncio.sleep(sleep_seconds)

    asyncio.run(_runner())


if __name__ == "__main__":
    app()
