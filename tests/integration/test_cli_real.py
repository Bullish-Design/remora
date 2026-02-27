from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.helpers import (
    agentfs_available_sync,
    load_vllm_config,
    vllm_available,
    write_bundle,
    write_config,
)


pytestmark = pytest.mark.integration


def test_cli_run_real(tmp_path: Path) -> None:
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

    config_path = tmp_path / "remora.yaml"
    write_config(
        config_path,
        {
            "bundles": {"path": str(bundle_dir), "mapping": {"function": bundle_path.name}},
            "model": {
                "base_url": vllm_config["base_url"],
                "api_key": vllm_config["api_key"],
                "default_model": vllm_config["model"],
            },
            "execution": {"max_turns": 2, "timeout": 120},
            "workspace": {"base_path": str(tmp_path / "workspaces")},
        },
    )

    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "remora",
            "run",
            str(target_file),
            "--config",
            str(config_path),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )

    assert result.returncode == 0, result.stderr
    assert "Completed" in result.stdout
