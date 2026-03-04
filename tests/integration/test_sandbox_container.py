"""Integration tests for WorkspaceSandbox + DockerRuntime against the real container.

These tests require:
  1. Docker daemon running
  2. remora-sandbox:latest image built (see sandbox/build.sh)

Tests are skipped if either condition is not met.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from remora.workspace.sandbox import (
    DockerRuntime,
    ExecutionResult,
    SandboxConfig,
    WorkspaceSandbox,
)

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_docker_available = shutil.which("docker") is not None


def _image_exists(name: str = "remora-sandbox:latest") -> bool:
    """Check if a Docker image exists locally."""
    if not _docker_available:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", name],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


_image_ready = _image_exists()

skip_no_docker = pytest.mark.skipif(
    not _docker_available,
    reason="Docker not available",
)
skip_no_image = pytest.mark.skipif(
    not _image_ready,
    reason="remora-sandbox:latest image not built (run sandbox/build.sh)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temp workspace with a simple Python file and test."""
    (tmp_path / "hello.py").write_text('def greet(name: str) -> str:\n    return f"Hello, {name}!"\n')
    (tmp_path / "test_hello.py").write_text(
        'from hello import greet\n\ndef test_greet():\n    assert greet("world") == "Hello, world!"\n'
    )
    return tmp_path


@pytest.fixture
def bad_workspace(tmp_path: Path) -> Path:
    """Create a workspace with intentional errors."""
    (tmp_path / "bad_types.py").write_text(
        "def add(a: int, b: int) -> str:\n    return a + b  # returns int, not str\n"
    )
    (tmp_path / "bad_lint.py").write_text("import os\nimport sys\nimport os  # duplicate\nx=1\n")
    (tmp_path / "syntax_error.py").write_text("def broken(\n    # missing closing paren\n")
    return tmp_path


# ---------------------------------------------------------------------------
# DockerRuntime integration tests
# ---------------------------------------------------------------------------


@skip_no_docker
@skip_no_image
class TestDockerRuntimeIntegration:
    """Test DockerRuntime against the real Docker daemon."""

    @pytest.mark.asyncio
    async def test_basic_python(self) -> None:
        """Run a simple Python command in the container."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["python", "-c", "print('hello from sandbox')"],
            timeout=30.0,
        )
        assert result.exit_code == 0
        assert "hello from sandbox" in result.stdout
        assert result.duration > 0

    @pytest.mark.asyncio
    async def test_pytest_available(self) -> None:
        """Verify pytest is installed in the container."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["pytest", "--version"],
            timeout=30.0,
        )
        assert result.exit_code == 0
        assert "pytest" in result.stdout

    @pytest.mark.asyncio
    async def test_mypy_available(self) -> None:
        """Verify mypy is installed in the container."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["mypy", "--version"],
            timeout=30.0,
        )
        assert result.exit_code == 0
        assert "mypy" in result.stdout

    @pytest.mark.asyncio
    async def test_ruff_available(self) -> None:
        """Verify ruff is installed in the container."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["ruff", "--version"],
            timeout=30.0,
        )
        assert result.exit_code == 0
        assert "ruff" in result.stdout

    @pytest.mark.asyncio
    async def test_network_isolation(self) -> None:
        """Container should work with --network none (air-gapped)."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["python", "-c", "print('air-gapped')"],
            network=False,
            timeout=30.0,
        )
        assert result.exit_code == 0
        assert "air-gapped" in result.stdout

    @pytest.mark.asyncio
    async def test_read_only_filesystem(self) -> None:
        """Container should work with --read-only filesystem."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["python", "-c", "print('read-only works')"],
            read_only=True,
            timeout=30.0,
        )
        assert result.exit_code == 0
        assert "read-only works" in result.stdout

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self) -> None:
        """Container should propagate nonzero exit codes."""
        rt = DockerRuntime()
        result = await rt.run(
            "remora-sandbox:latest",
            ["python", "-c", "import sys; sys.exit(42)"],
            timeout=30.0,
        )
        assert result.exit_code == 42


# ---------------------------------------------------------------------------
# WorkspaceSandbox integration tests
# ---------------------------------------------------------------------------


@skip_no_docker
@skip_no_image
class TestWorkspaceSandboxIntegration:
    """Test WorkspaceSandbox with real DockerRuntime."""

    @pytest.mark.asyncio
    async def test_exec_in_workspace(self, workspace: Path) -> None:
        """Execute a command that reads files from the mounted workspace."""
        sandbox = WorkspaceSandbox(workspace)
        result = await sandbox.exec("ls -1", timeout=30.0)

        assert result.exit_code == 0
        assert "hello.py" in result.stdout
        assert "test_hello.py" in result.stdout

    @pytest.mark.asyncio
    async def test_run_pytest(self, workspace: Path) -> None:
        """Run pytest against the mounted workspace."""
        sandbox = WorkspaceSandbox(workspace)
        result = await sandbox.exec(
            ["pytest", "-q", "test_hello.py"],
            timeout=30.0,
        )

        assert result.exit_code == 0
        assert "1 passed" in result.stdout

    @pytest.mark.asyncio
    async def test_run_mypy(self, workspace: Path) -> None:
        """Run mypy type checking on workspace files."""
        sandbox = WorkspaceSandbox(workspace)
        result = await sandbox.exec(
            ["mypy", "hello.py"],
            timeout=30.0,
        )

        assert result.exit_code == 0
        assert "Success" in result.stdout

    @pytest.mark.asyncio
    async def test_run_ruff(self, workspace: Path) -> None:
        """Run ruff linting on workspace files."""
        sandbox = WorkspaceSandbox(workspace)
        result = await sandbox.exec(
            ["ruff", "check", "hello.py"],
            timeout=30.0,
        )

        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_mypy_detects_type_error(self, bad_workspace: Path) -> None:
        """Mypy should detect the type error in bad_types.py."""
        sandbox = WorkspaceSandbox(bad_workspace)
        result = await sandbox.exec(
            ["mypy", "bad_types.py"],
            timeout=30.0,
        )

        assert result.exit_code != 0
        assert "error" in result.stdout.lower() or "error" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_ruff_detects_lint_issues(self, bad_workspace: Path) -> None:
        """Ruff should detect lint issues in bad_lint.py."""
        sandbox = WorkspaceSandbox(bad_workspace)
        result = await sandbox.exec(
            ["ruff", "check", "bad_lint.py"],
            timeout=30.0,
        )

        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_python_detects_syntax_error(self, bad_workspace: Path) -> None:
        """Python should fail on syntax_error.py."""
        sandbox = WorkspaceSandbox(bad_workspace)
        result = await sandbox.exec(
            ["python", "-m", "py_compile", "syntax_error.py"],
            timeout=30.0,
        )

        assert result.exit_code != 0

    @pytest.mark.asyncio
    async def test_custom_config(self, workspace: Path) -> None:
        """Custom config values should work end-to-end."""
        config = SandboxConfig(
            memory_limit="256m",
            cpu_limit=0.5,
            env={"GREETING": "hi"},
        )
        sandbox = WorkspaceSandbox(workspace, config=config)
        result = await sandbox.exec(
            ["python", "-c", "import os; print(os.environ.get('GREETING', 'missing'))"],
            timeout=30.0,
        )

        assert result.exit_code == 0
        assert "hi" in result.stdout

    @pytest.mark.asyncio
    async def test_write_to_workspace(self, workspace: Path) -> None:
        """Container should be able to write files to the mounted workspace."""
        sandbox = WorkspaceSandbox(workspace)
        result = await sandbox.exec(
            ["python", "-c", "open('output.txt', 'w').write('created')"],
            timeout=30.0,
        )

        assert result.exit_code == 0
        output_file = workspace / "output.txt"
        assert output_file.exists()
        assert output_file.read_text() == "created"

    @pytest.mark.asyncio
    async def test_air_gapped_validation(self, workspace: Path) -> None:
        """Full validation pipeline should work without network."""
        sandbox = WorkspaceSandbox(workspace)

        # All three tools should work air-gapped (network=False is default)
        for cmd in [
            ["python", "-c", "import ast; ast.parse(open('hello.py').read()); print('syntax ok')"],
            ["mypy", "hello.py"],
            ["ruff", "check", "hello.py"],
            ["pytest", "-q", "test_hello.py"],
        ]:
            result = await sandbox.exec(cmd, timeout=30.0)
            assert result.exit_code == 0, f"Failed: {cmd} — stderr: {result.stderr}"
