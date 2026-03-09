from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.bootstrap.seed_graph import (
    seed_coordinator_node,
    seed_module_nodes_from_filesystem,
    seed_modules_if_empty,
)
from remora.core.code.projections import NodeProjection
from remora.core.events.code_events import NodeDiscoveredEvent
from remora.core.store.event_store import EventStore

SKIP_DIRS = [".venv", ".devenv", "__pycache__", "dist", "build", ".git"]


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await event_store.initialize()
    yield event_store
    await event_store.close()


@pytest.mark.asyncio
async def test_seed_from_filesystem_creates_module_nodes(tmp_path: Path, store: EventStore) -> None:
    (tmp_path / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "bar.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "skip.py").write_text("z = 3\n", encoding="utf-8")

    created = await seed_module_nodes_from_filesystem(store, tmp_path, swarm_id="swarm")
    assert created == 2

    rows_raw = await store.nodes.read_graph({"match": {"kind": "module"}})
    rows = json.loads(rows_raw)
    ids = {row["id"] for row in rows}
    assert ids == {"module:foo.py", "module:pkg/bar.py"}


@pytest.mark.asyncio
async def test_seed_modules_if_empty_skips_when_live_nodes_exist(tmp_path: Path, store: EventStore) -> None:
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="module:existing.py",
            node_type="file",
            name="existing.py",
            full_name="existing",
            file_path="existing.py",
            start_line=1,
            end_line=1,
            source_code="pass\n",
            source_hash="hash",
        ),
    )

    (tmp_path / "new.py").write_text("x = 1\n", encoding="utf-8")
    created = await seed_modules_if_empty(store, tmp_path, swarm_id="swarm")
    assert created == 0

    rows_raw = await store.nodes.read_graph({"match": {"kind": "module"}})
    rows = json.loads(rows_raw)
    assert len(rows) == 1
    assert rows[0]["id"] == "module:existing.py"


@pytest.mark.asyncio
async def test_seed_coordinator_node_creates_agent_graph_node(store: EventStore) -> None:
    await seed_coordinator_node(store, coordinator_id="coordinator")
    node_raw = await store.nodes.read_graph({"node": "coordinator"})
    node = json.loads(node_raw)

    assert node["kind"] == "agent"
    assert node["attrs"]["name"] == "coordinator"


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_dir", SKIP_DIRS)
async def test_skip_dirs_are_excluded(tmp_path: Path, skip_dir: str) -> None:
    skip_path = tmp_path / skip_dir
    skip_path.mkdir()
    (skip_path / "module_that_should_be_skipped.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "real_module.py").write_text("y = 2\n", encoding="utf-8")

    event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await event_store.initialize()
    try:
        count = await seed_module_nodes_from_filesystem(
            event_store,
            tmp_path,
            swarm_id="swarm",
        )
        assert count == 1
    finally:
        await event_store.close()
