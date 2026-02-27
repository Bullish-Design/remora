from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fsdantic import Fsdantic

from remora.indexer.daemon import IndexerConfig, IndexerDaemon
from remora.indexer.store import NodeStateStore
from tests.integration.helpers import agentfs_available


pytestmark = pytest.mark.integration


async def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.1) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("Timed out waiting for condition")


def _write_sample(path: Path, *, include_beta: bool) -> None:
    lines = [
        "def alpha():",
        "    return 1",
        "",
    ]
    if include_beta:
        lines.extend(
            [
                "def beta():",
                "    return 2",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.mark.asyncio
async def test_indexer_daemon_cold_start_and_incremental_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")

    project_root = tmp_path / "project"
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True)
    target_file = src_dir / "sample.py"
    _write_sample(target_file, include_beta=False)
    monkeypatch.chdir(project_root)

    db_path = project_root / "indexer.db"
    workspace = await Fsdantic.open(path=str(db_path))
    store = NodeStateStore(workspace)

    config = IndexerConfig(
        watch_paths=["src"],
        store_path="indexer.db",
        max_workers=1,
    )
    daemon = IndexerDaemon(config, store=store)
    daemon.project_root = project_root

    task = asyncio.create_task(daemon.start())

    async def _has_alpha() -> bool:
        nodes = await store.get_by_file(str(target_file))
        return any(node.node_name == "alpha" for node in nodes)

    await _wait_for(_has_alpha, timeout=5)

    file_index_before = await store.get_file_index(str(target_file))
    assert file_index_before is not None
    assert file_index_before.node_count == 1

    _write_sample(target_file, include_beta=True)

    async def _has_beta() -> bool:
        nodes = await store.get_by_file(str(target_file))
        return any(node.node_name == "beta" for node in nodes)

    await _wait_for(_has_beta, timeout=5)

    file_index_after = await store.get_file_index(str(target_file))
    assert file_index_after is not None
    assert file_index_after.node_count == 2
    assert file_index_after.file_hash != file_index_before.file_hash

    target_file.unlink()

    async def _deleted() -> bool:
        nodes = await store.get_by_file(str(target_file))
        file_index = await store.get_file_index(str(target_file))
        return not nodes and file_index is None

    await _wait_for(_deleted, timeout=5)

    await daemon._shutdown()
    await asyncio.wait_for(task, timeout=5)
    await workspace.close()
