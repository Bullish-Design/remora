from __future__ import annotations

from pathlib import Path

from remora.companion.config import IndexingConfig


def test_indexing_config_resolves_relative_store_path_against_workspace() -> None:
    cfg = IndexingConfig()

    resolved = cfg.resolve_store_db_path(Path("/tmp/remora-workspace"))

    assert resolved == Path("/tmp/remora-workspace/.remora/companion/vectors.db")


def test_indexing_config_preserves_absolute_store_path() -> None:
    cfg = IndexingConfig(store={"db_path": "/var/tmp/custom-vectors.db"})

    resolved = cfg.resolve_store_db_path(Path("/tmp/remora-workspace"))

    assert resolved == Path("/var/tmp/custom-vectors.db")
