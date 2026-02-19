from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
import shutil
import subprocess
import sys
import urllib.request

import pytest

from remora.config import ServerConfig

SERVER_URL = os.environ.get("REMORA_SERVER_URL", "http://remora-server:8000/v1")
SERVER = ServerConfig(base_url=SERVER_URL)


def _server_available(server: ServerConfig) -> bool:
    try:
        with urllib.request.urlopen(f"{server.base_url}/models", timeout=2) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    model_ids = {item.get("id") for item in payload.get("data", []) if isinstance(item, dict)}
    return server.default_adapter in model_ids


@dataclass
class LocalGrailExecutor:
    base_dir: Path
    target_relpath: Path

    async def execute(
        self,
        pym_path: Path,
        grail_dir: Path,
        inputs: dict[str, Any],
        limits: dict[str, Any] | None = None,
        agent_id: str | None = None,
        workspace_path: Path | None = None,
        stable_path: Path | None = None,
        node_source: str | None = None,
        node_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a tool in the local environment."""
        # Use the provided grail_dir as the workspace
        workspace_dir = grail_dir
        workspace_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["REMORA_WORKSPACE_DIR"] = str(workspace_dir)
        env["REMORA_WORKSPACE_ID"] = agent_id or "default"
        env["REMORA_TARGET_FILE"] = str(self.target_relpath)
        
        if node_source:
             env["REMORA_NODE_TEXT"] = node_source
             remora_dir = workspace_dir / ".remora"
             remora_dir.mkdir(parents=True, exist_ok=True)
             (remora_dir / "node_text").write_text(node_source, encoding="utf-8")
        
        env["REMORA_INPUT"] = json.dumps(inputs)
        
        cmd = [sys.executable, str(pym_path)]
        
        completed = subprocess.run(
            cmd,
            cwd=str(workspace_dir),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        
        if completed.returncode != 0:
            return {"error": completed.stderr.strip() or f"tool exit code {completed.returncode}"}
        
        output = completed.stdout.strip()
        if not output:
             return {}
        try:
             return json.loads(output)
        except json.JSONDecodeError:
             return {"error": "Invalid JSON output", "output": output}

    def setup_workspace(self, workspace_dir: Path, node_text: str | None = None) -> None:
        """Helper to populate a workspace from the stable directory."""
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        stable_dir = self.base_dir / "stable"
        shutil.copytree(stable_dir, workspace_dir)
        
        remora_dir = workspace_dir / ".remora"
        remora_dir.mkdir(parents=True, exist_ok=True)
        (remora_dir / "target_file").write_text(str(self.target_relpath), encoding="utf-8")
        if node_text:
            (remora_dir / "node_text").write_text(node_text, encoding="utf-8")
        
    def get_workspace_dir(self, workspace_id: str) -> Path:
        """Stub for compatibility if needed, but tests should manage dirs."""
        return self.base_dir / workspace_id


@pytest.fixture()
def integration_workspace(tmp_path: Path) -> tuple[Path, Path]:
    base_dir = tmp_path / "cairn"
    stable_dir = base_dir / "stable"
    stable_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = Path(__file__).parent / "fixtures" / "integration_target.py"
    target_relpath = Path("tests/fixtures/integration_target.py")
    target_path = stable_dir / target_relpath
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(fixture_path.read_text(encoding="utf-8"), encoding="utf-8")
    (stable_dir / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (stable_dir / "tests" / "fixtures" / "__init__.py").write_text("", encoding="utf-8")
    return base_dir, target_relpath


@pytest.fixture()
def grail_executor_factory(integration_workspace: tuple[Path, Path]):
    base_dir, target_relpath = integration_workspace

    def _factory() -> LocalGrailExecutor:
        return LocalGrailExecutor(base_dir=base_dir, target_relpath=target_relpath)

    return _factory


@pytest.fixture(scope="session")
def vllm_available() -> bool:
    return _server_available(SERVER)


@pytest.fixture(autouse=True)
def skip_integration_if_unavailable(vllm_available: bool, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration") and not vllm_available:
        pytest.skip(f"vLLM server not reachable at {SERVER.base_url}")


@pytest.fixture
def llm_logger(tmp_path: Path):
    from remora.llm_logger import LlmConversationLogger
    logger = LlmConversationLogger(output=tmp_path / "llm_conversations.log")
    logger.open()
    yield logger
    logger.close()
