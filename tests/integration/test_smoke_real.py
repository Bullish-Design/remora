from __future__ import annotations

from pathlib import Path

import pytest
from structured_agents.events import ModelResponseEvent

from remora.core.cairn_bridge import CairnWorkspaceService
from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.executor import GraphExecutor
from remora.core.graph import build_graph
from remora.core.tools.grail import RemoraGrailTool
from remora.utils import PathResolver
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


@pytest.mark.asyncio
async def test_vllm_graph_executor_smoke(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
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
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
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
