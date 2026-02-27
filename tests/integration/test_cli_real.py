from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

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
        env=_cli_env(repo_root),
        capture_output=True,
        text=True,
        timeout=240,
    )

    assert result.returncode == 0, result.stderr
    assert "Completed" in result.stdout


def _cli_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_cli_run_invalid_config_fails(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    config_path = tmp_path / "remora.yaml"
    config_path.write_text("bundles: [invalid", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[2]
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
        env=_cli_env(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "Invalid YAML" in (result.stderr + result.stdout)


def test_cli_run_missing_bundle_mapping_fails(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    config_path = tmp_path / "remora.yaml"
    write_config(
        config_path,
        {
            "bundles": {"path": str(tmp_path), "mapping": {}},
            "execution": {"max_turns": 1, "timeout": 1},
            "workspace": {"base_path": str(tmp_path / "workspaces")},
        },
    )

    repo_root = Path(__file__).resolve().parents[2]
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
        env=_cli_env(repo_root),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "No bundle mapping configured" in (result.stderr + result.stdout)


def test_dashboard_cli_run_serves_http(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    port = _get_free_port()

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "remora.dashboard.cli",
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=repo_root,
        env=_cli_env(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        deadline = time.time() + 10
        last_error = None
        while time.time() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    assert response.status == 200
                    return
            except Exception as exc:
                last_error = exc
                time.sleep(0.2)
        raise AssertionError(f"Dashboard did not start: {last_error}")
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
