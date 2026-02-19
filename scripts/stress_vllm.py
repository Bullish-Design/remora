"""Stress test the vLLM endpoint by running Remora agents in parallel."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from remora.config import RemoraConfig, OperationConfig, load_config
from remora.discovery import TreeSitterDiscoverer, CSTNode
from remora.orchestrator import Coordinator
from remora.results import NodeResult
from pydantic import ValidationError
import typer

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stress_test")

app = typer.Typer(help="Stress test vLLM with parallel Remora agents.")


def _demo_root() -> Path:
    # Assuming this script is in remora/scripts/
    return Path(__file__).resolve().parents[1].joinpath("training", "demo_project")


def _build_test_config(base: RemoraConfig, concurrency: int) -> RemoraConfig:
    # Ensure enough concurrency in Cairn config
    cairn_config = base.cairn.model_copy(update={"max_concurrent_agents": concurrency})

    # Use a single simple operation for the test
    ops: dict[str, OperationConfig] = {}
    if "lint" in base.operations:
        ops["lint"] = base.operations["lint"]
    else:
        ops["lint"] = OperationConfig(subagent="lint/lint_subagent.yaml")

    return base.model_copy(
        update={
            "cairn": cairn_config,
            "operations": ops,
        }
    )


def _collect_nodes(config: RemoraConfig, demo_root: Path) -> list[CSTNode]:
    logger.info(f"Discovering nodes in {demo_root}...")
    discoverer = TreeSitterDiscoverer(
        root_dirs=[demo_root],
        # Use defaults from config or provide them if missing
        language=config.discovery.language,
        query_pack=config.discovery.query_pack,
        query_dir=config.discovery.query_dir,
    )
    nodes = discoverer.discover()
    logger.info(f"Found {len(nodes)} unique nodes in project.")
    return nodes


async def _run_stress_test(concurrency: int, max_nodes: int) -> None:
    demo_root = _demo_root()
    base_config = load_config(None, overrides=None)

    # Adjust config for the test
    config = _build_test_config(base_config, concurrency)

    # 1. Discover nodes from the demo project
    nodes = _collect_nodes(config, demo_root)

    if not nodes:
        logger.error("No nodes found to process!")
        return

    # 2. Duplicate nodes to reach the requested 'max_nodes' count
    # This ensures we have enough work to actually test concurrency
    working_nodes: list[CSTNode] = []
    while len(working_nodes) < max_nodes:
        working_nodes.extend(nodes)

    # Truncate to exact count
    working_nodes = working_nodes[:max_nodes]

    logger.info("-" * 40)
    logger.info(f"Starting Stress Test")
    logger.info(f"  Concurrency: {concurrency}")
    logger.info(f"  Total Tasks: {len(working_nodes)}")
    logger.info("-" * 40)

    start_time = time.monotonic()

    # The Coordinator handles the semaphore for concurrency, but we need to
    # create all the tasks upfront so they can be scheduled.
    async with Coordinator(config=config, event_stream_enabled=False) as coordinator:
        operations = list(config.operations.keys())

        # Launch all tasks. The coordinator execution semaphore will queue them.
        tasks = [asyncio.create_task(coordinator.process_node(node, operations)) for node in working_nodes]

        logger.info(f"Queued {len(tasks)} tasks...")

        # Wait for all to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

    end_time = time.monotonic()
    duration = end_time - start_time

    # --- Results Analysis ---
    success_count = 0
    error_count = 0

    for res in results:
        if isinstance(res, Exception):
            error_count += 1
        elif isinstance(res, NodeResult):
            # Check if the node result has internal errors
            if res.errors:
                error_count += 1
            else:
                success_count += 1
        else:
            # Unknown result type
            error_count += 1

    throughput = len(working_nodes) / duration if duration > 0 else 0

    logger.info("-" * 40)
    logger.info(f"Stress Test Completed")
    logger.info("-" * 40)
    logger.info(f"  Concurrency: {concurrency}")
    logger.info(f"  Time Taken:  {duration:.2f}s")
    logger.info(f"  Throughput:  {throughput:.2f} nodes/sec")
    logger.info(f"  Success:     {success_count}")
    logger.info(f"  Errors:      {error_count}")
    logger.info("-" * 40)


@app.command()
def main(
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Max concurrent agents"),
    nodes: int = typer.Option(
        20, "--nodes", "-n", help="Total number of nodes to process (duplicated from demo if needed)"
    ),
) -> None:
    """Run the Remora vLLM stress test."""
    asyncio.run(_run_stress_test(concurrency, nodes))


if __name__ == "__main__":
    app()
