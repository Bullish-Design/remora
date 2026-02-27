from __future__ import annotations

import asyncio
import queue
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.dashboard.app import create_app
from remora.event_bus import EventBus
from tests.integration.helpers import agentfs_available_sync, load_vllm_config, vllm_available, write_bundle


pytestmark = pytest.mark.integration


def test_dashboard_run_emits_events(tmp_path: Path) -> None:
    if not agentfs_available_sync():
        pytest.skip("AgentFS not reachable")
    vllm_config = load_vllm_config()
    if not vllm_available(vllm_config["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    bundle_dir = tmp_path / "smoke_bundle"
    bundle_path = write_bundle(bundle_dir)

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=vllm_config["base_url"],
            api_key=vllm_config["api_key"],
            default_model=vllm_config["model"],
        ),
        execution=ExecutionConfig(max_turns=2, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    events: queue.Queue[object] = queue.Queue()

    def _record(event: object) -> None:
        events.put(event)

    event_bus.subscribe_all(_record)

    app = asyncio.run(create_app(event_bus=event_bus, config=config))

    with TestClient(app) as client:
        response = client.post(
            "/run",
            json={"target_path": str(target_file), "bundle": "function"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("status") == "started"

        deadline = time.time() + 120
        found = False
        while time.time() < deadline:
            try:
                event = events.get(timeout=1)
            except queue.Empty:
                continue
            if type(event).__name__ in {"AgentCompleteEvent", "GraphCompleteEvent"}:
                found = True
                break

        assert found
