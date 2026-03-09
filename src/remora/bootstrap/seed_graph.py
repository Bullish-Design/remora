"""Bootstrap graph seeding helpers.

Seeds non-code bootstrap nodes and provides a lightweight filesystem fallback
for module nodes when the normal scanner projection has not populated `nodes`.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from remora.core.code.projections import NodeProjection
from remora.core.events.code_events import NodeDiscoveredEvent
from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)

# Default skip directories for Python project layouts. Pass skip_dirs= to
# seed_module_nodes_from_filesystem() or seed_modules_if_empty() to override.
_SKIP_DIRS = frozenset({".venv", ".devenv", "__pycache__", "dist", "build", ".git"})


def _module_full_name(rel_path: str) -> str:
    module_path = rel_path
    if module_path.startswith("src/"):
        module_path = module_path[len("src/") :]
    return module_path.replace("/", ".").removesuffix(".py")


async def seed_module_nodes_from_filesystem(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
    skip_dirs: frozenset[str] | None = None,
) -> int:
    """Create file/module nodes in `nodes` via NodeDiscoveredEvent projection.

    Args:
        skip_dirs: Optional override for directory names excluded from scan.
    """
    root = project_root.resolve()
    created = 0
    effective_skip = skip_dirs if skip_dirs is not None else _SKIP_DIRS

    for py_file in sorted(root.rglob("*.py")):
        rel_path_obj = py_file.relative_to(root)
        if effective_skip.intersection(rel_path_obj.parts):
            continue

        rel_path = rel_path_obj.as_posix()
        node_id = f"module:{rel_path}"
        if await event_store.nodes.get_node(node_id):
            continue

        source = py_file.read_text(encoding="utf-8", errors="replace")
        source_bytes = source.encode("utf-8")
        source_hash = hashlib.sha1(source_bytes).hexdigest()
        line_count = source.count("\n") + 1
        byte_count = len(source_bytes)

        await event_store.append(
            swarm_id,
            NodeDiscoveredEvent(
                node_id=node_id,
                node_type="file",
                name=py_file.stem,
                full_name=_module_full_name(rel_path),
                file_path=rel_path,
                start_line=1,
                end_line=max(1, line_count),
                start_byte=0,
                end_byte=byte_count,
                source_code=source,
                source_hash=source_hash,
            ),
        )
        created += 1

    logger.info("Seeded %d module nodes from filesystem fallback", created)
    return created


async def seed_coordinator_node(
    event_store: EventStore,
    *,
    coordinator_id: str = "coordinator",
) -> None:
    """Ensure the bootstrap coordinator node exists in the graph."""
    await event_store.nodes.write_graph(
        "add_node",
        {
            "id": coordinator_id,
            "kind": "agent",
            "attrs": {
                "name": "coordinator",
                "role": "Surveys graph and emits AgentNeededEvent for unassigned modules",
                "status": "pending",
            },
        },
    )
    logger.info("Seeded coordinator node: %s", coordinator_id)


async def seed_modules_if_empty(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
    skip_dirs: frozenset[str] | None = None,
) -> int:
    """Seed module nodes only when no module/file nodes currently exist."""
    existing = await event_store.nodes.read_graph({"match": {"kind": "module"}})
    if existing and existing != "[]":
        logger.info("Module nodes already exist; skipping filesystem seeding")
        return 0
    return await seed_module_nodes_from_filesystem(
        event_store,
        project_root,
        swarm_id=swarm_id,
        skip_dirs=skip_dirs,
    )


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)

    project_root = Path.cwd()
    event_store_path = project_root / ".remora" / "events" / "events.db"
    event_store = EventStore(event_store_path, projection=NodeProjection())
    await event_store.initialize()
    try:
        await seed_coordinator_node(event_store)
        await seed_modules_if_empty(event_store, project_root, swarm_id="bootstrap")
    finally:
        await event_store.close()


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = [
    "seed_module_nodes_from_filesystem",
    "seed_coordinator_node",
    "seed_modules_if_empty",
]
