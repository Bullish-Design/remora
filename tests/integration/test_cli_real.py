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

pytestmark = pytest.mark.integration


def _cli_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    return env


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _uvicorn_available() -> bool:
    try:
        import uvicorn  # noqa: F401
    except Exception:
        return False
    return True


def test_service_cli_serve_serves_http(tmp_path: Path) -> None:
    if not _uvicorn_available():
        pytest.skip("uvicorn is not available")

    repo_root = Path(__file__).resolve().parents[2]
    port = _get_free_port()

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "remora",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=repo_root,
        env=_cli_env(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.time() + 10
        last_error: Exception | None = None
        while time.time() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=2)
                raise AssertionError(
                    "Service exited early "
                    f"(code={process.returncode}) stdout={stdout!r} stderr={stderr!r}"
                )
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    assert response.status == 200
                    return
            except Exception as exc:  # pragma: no cover - best-effort probe
                last_error = exc
                time.sleep(0.2)
        raise AssertionError(f"Service did not start: {last_error}")
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()


def test_cli_serve_invalid_config_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_remora.yaml"
    config_path.write_text("bundles: [invalid", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "remora",
            "serve",
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
