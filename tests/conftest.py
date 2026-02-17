from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import urllib.request

import pytest

SERVER_URL = os.environ.get("REMORA_SERVER_URL", "http://function-gemma-server:8000/v1")


def _server_available(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


@dataclass
class LocalCairnClient:
    base_dir: Path
    target_relpath: Path
    node_text: str | None = None

    def __post_init__(self) -> None:
        self.stable_dir = self.base_dir / "stable"
        self._workspaces: dict[str, Path] = {}

    def workspace_path(self, workspace_id: str) -> Path:
        return self._ensure_workspace(workspace_id)

    async def run_pym(self, path: object, workspace_id: str, inputs: dict[str, object]) -> object:
        workspace_dir = self._ensure_workspace(workspace_id)
        env = os.environ.copy()
        env["REMORA_WORKSPACE_DIR"] = str(workspace_dir)
        env["REMORA_WORKSPACE_ID"] = workspace_id
        env["REMORA_TARGET_FILE"] = str(self.target_relpath)
        if self.node_text:
            env["REMORA_NODE_TEXT"] = self.node_text
            remora_dir = workspace_dir / ".remora"
            remora_dir.mkdir(parents=True, exist_ok=True)
            (remora_dir / "node_text").write_text(self.node_text, encoding="utf-8")
        env["REMORA_INPUT"] = json.dumps(inputs)

        completed = subprocess.run(
            [sys.executable, str(path)],
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
            return output

    def _ensure_workspace(self, workspace_id: str) -> Path:
        if workspace_id in self._workspaces:
            return self._workspaces[workspace_id]
        workspace_dir = self.base_dir / workspace_id
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        shutil.copytree(self.stable_dir, workspace_dir)
        remora_dir = workspace_dir / ".remora"
        remora_dir.mkdir(parents=True, exist_ok=True)
        (remora_dir / "target_file").write_text(str(self.target_relpath), encoding="utf-8")
        if self.node_text:
            (remora_dir / "node_text").write_text(self.node_text, encoding="utf-8")
        self._workspaces[workspace_id] = workspace_dir
        return workspace_dir


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
def cairn_client_factory(integration_workspace: tuple[Path, Path]):
    base_dir, target_relpath = integration_workspace

    def _factory(node_text: str | None = None) -> LocalCairnClient:
        return LocalCairnClient(base_dir=base_dir, target_relpath=target_relpath, node_text=node_text)

    return _factory


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if not _server_available(SERVER_URL):
        skip = pytest.mark.skip(reason=f"vLLM server not reachable at {SERVER_URL}")
        for item in items:
            if item.get_closest_marker("integration"):
                item.add_marker(skip)
