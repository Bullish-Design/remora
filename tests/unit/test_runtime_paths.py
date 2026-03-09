from __future__ import annotations

from pathlib import Path

from remora.core.config import Config
from remora.core.runtime_paths import RuntimePaths


def test_runtime_paths_defaults_to_project_relative_layout(tmp_path: Path) -> None:
    config = Config(project_path=str(tmp_path), swarm_root=".remora", swarm_id="swarm")
    paths = RuntimePaths.from_config(config)

    assert paths.project_root == tmp_path
    assert paths.swarm_root == tmp_path / ".remora"
    assert paths.event_store_path == tmp_path / ".remora" / "events" / "events.db"
    assert paths.subscriptions_path == tmp_path / ".remora" / "subscriptions.db"
    assert paths.models_root == tmp_path / ".remora" / "models"
    assert paths.bootstrap_root == tmp_path / "bootstrap"


def test_runtime_paths_respects_absolute_overrides(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    swarm_root = tmp_path / "custom_swarm"
    bootstrap_root = tmp_path / "custom_bootstrap"

    config = Config(
        project_path=str(project_root),
        swarm_root=str(swarm_root),
        swarm_id="swarm",
    )
    paths = RuntimePaths.from_config(config, bootstrap_root=bootstrap_root)

    assert paths.project_root == project_root
    assert paths.swarm_root == swarm_root
    assert paths.event_store_path == swarm_root / "events" / "events.db"
    assert paths.subscriptions_path == swarm_root / "subscriptions.db"
    assert paths.bootstrap_root == bootstrap_root
