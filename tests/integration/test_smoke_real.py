from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import pytest
import yaml
from structured_agents.events import ModelResponseEvent

from remora.cairn_bridge import CairnWorkspaceService
from remora.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.discovery import discover
from remora.event_bus import EventBus
from remora.executor import GraphExecutor
from remora.graph import build_graph
from remora.tools.grail import RemoraGrailTool
from remora.utils import PathResolver


pytestmark = pytest.mark.integration

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "vllm_server.yaml"


def _load_vllm_config() -> dict[str, str]:
    config = {
        "base_url": "http://remora-server:8000/v1",
        "api_key": "EMPTY",
        "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
    }

    if CONFIG_PATH.exists():
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        for key in ("base_url", "api_key", "model"):
            value = data.get(key)
            if value:
                config[key] = str(value)

    base_url = os.environ.get("REMORA_TEST_VLLM_BASE_URL")
    if base_url:
        config["base_url"] = base_url
    api_key = os.environ.get("REMORA_TEST_VLLM_API_KEY")
    if api_key:
        config["api_key"] = api_key
    model = os.environ.get("REMORA_TEST_VLLM_MODEL")
    if model:
        config["model"] = model

    return config


VLLM_CONFIG = _load_vllm_config()


def _vllm_available(base_url: str) -> bool:
    url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def _write_bundle(bundle_dir: Path) -> Path:
    tools_dir = bundle_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "bundle.yaml"
    bundle_path.write_text(
        """
name: smoke_agent
model: qwen
initial_context:
  system_prompt: |
    You are a minimal smoke-test agent. Provide a short response.
agents_dir: tools
max_turns: 2
""".lstrip(),
        encoding="utf-8",
    )
    return bundle_path


@pytest.mark.asyncio
async def test_vllm_graph_executor_smoke(tmp_path: Path) -> None:
    if not _vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    bundle_dir = tmp_path / "smoke_bundle"
    bundle_path = _write_bundle(bundle_dir)

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=2, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "smoke-graph")

    assert results
    assert any(isinstance(event, ModelResponseEvent) for event in events)


@pytest.mark.asyncio
async def test_grail_tool_cairn_write_smoke(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    workspace_config = WorkspaceConfig(base_path=str(tmp_path / "workspaces"))
    service = CairnWorkspaceService(workspace_config, "grail-smoke", project_root=project_root)
    await service.initialize(sync=True)
    workspace = await service.get_agent_workspace("agent-1")
    externals = service.get_externals("agent-1", workspace)

    tool_path = tmp_path / "write_result.pym"
    tool_path.write_text(
        """
from grail import Input, external

path: str = Input("path")
content: str = Input("content")

@external
async def write_file(path: str, content: str) -> bool:
    ...

try:
    await write_file(path, content)
    result = {
        "summary": f"wrote {path}",
        "outcome": "success",
    }
except Exception as exc:
    result = {
        "summary": f"error: {exc}",
        "outcome": "error",
        "error": str(exc),
    }

result
""".lstrip(),
        encoding="utf-8",
    )

    async def files_provider() -> dict[str, str]:
        return {}

    tool = RemoraGrailTool(tool_path, externals=externals, files_provider=files_provider)

    target_path = project_root / "output.txt"
    result = await tool.execute({"path": str(target_path), "content": "hello"}, None)

    assert result.is_error is False

    resolver = PathResolver(project_root)
    workspace_path = resolver.to_workspace_path(target_path)
    content = await workspace.read(workspace_path)
    assert content == "hello"

    await service.close()
