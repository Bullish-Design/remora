"""Tests for remora.workspace.sandbox — container sandbox utilities."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.workspace.sandbox import (
    ContainerRuntime,
    DockerRuntime,
    ExecutionResult,
    SandboxConfig,
    WorkspaceSandbox,
)


# ---------------------------------------------------------------------------
# Mock Runtime
# ---------------------------------------------------------------------------


class MockRuntime(ContainerRuntime):
    """In-memory container runtime for testing."""

    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.calls: list[dict] = []
        self._result = result or ExecutionResult(exit_code=0, stdout="ok\n", stderr="", duration=0.5)

    async def run(
        self,
        image: str,
        command: list[str],
        *,
        volumes: dict[str, str] | None = None,
        env: dict[str, str] | None = None,
        workdir: str = "/workspace",
        memory: str = "512m",
        cpus: float = 1.0,
        network: bool = False,
        read_only: bool = False,
        timeout: float = 300.0,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "image": image,
                "command": command,
                "volumes": volumes,
                "env": env,
                "workdir": workdir,
                "memory": memory,
                "cpus": cpus,
                "network": network,
                "read_only": read_only,
                "timeout": timeout,
            }
        )
        return self._result


# ---------------------------------------------------------------------------
# SandboxConfig tests
# ---------------------------------------------------------------------------


class TestSandboxConfig:
    def test_defaults(self) -> None:
        cfg = SandboxConfig()
        assert cfg.image == "remora-sandbox:latest"
        assert cfg.memory_limit == "512m"
        assert cfg.cpu_limit == 1.0
        assert cfg.timeout == 300.0
        assert cfg.network is False
        assert cfg.read_only is False
        assert cfg.env == {}
        assert cfg.workdir == "/workspace"

    def test_custom_values(self) -> None:
        cfg = SandboxConfig(
            image="node:20",
            memory_limit="1g",
            cpu_limit=2.0,
            timeout=60.0,
            network=True,
            env={"FOO": "bar"},
        )
        assert cfg.image == "node:20"
        assert cfg.memory_limit == "1g"
        assert cfg.cpu_limit == 2.0
        assert cfg.timeout == 60.0
        assert cfg.network is True
        assert cfg.env == {"FOO": "bar"}


# ---------------------------------------------------------------------------
# ExecutionResult tests
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_success(self) -> None:
        r = ExecutionResult(exit_code=0, stdout="output", stderr="", duration=1.0)
        assert r.exit_code == 0
        assert r.timed_out is False

    def test_failure(self) -> None:
        r = ExecutionResult(exit_code=1, stdout="", stderr="error", duration=0.3)
        assert r.exit_code == 1

    def test_timeout(self) -> None:
        r = ExecutionResult(exit_code=-1, stdout="", stderr="timed out", duration=300.0, timed_out=True)
        assert r.timed_out is True


# ---------------------------------------------------------------------------
# ContainerRuntime tests
# ---------------------------------------------------------------------------


class TestContainerRuntime:
    @pytest.mark.asyncio
    async def test_base_raises_not_implemented(self) -> None:
        rt = ContainerRuntime()
        with pytest.raises(NotImplementedError):
            await rt.run("image", ["cmd"])


class TestMockRuntime:
    @pytest.mark.asyncio
    async def test_records_calls(self) -> None:
        rt = MockRuntime()
        result = await rt.run(
            "python:3.12-slim",
            ["python", "-c", "print('hi')"],
            volumes={"/tmp/test": "/workspace"},
            env={"X": "1"},
            memory="256m",
            cpus=0.5,
            timeout=10.0,
        )
        assert result.exit_code == 0
        assert len(rt.calls) == 1
        call = rt.calls[0]
        assert call["image"] == "python:3.12-slim"
        assert call["command"] == ["python", "-c", "print('hi')"]
        assert call["volumes"] == {"/tmp/test": "/workspace"}
        assert call["env"] == {"X": "1"}
        assert call["memory"] == "256m"
        assert call["cpus"] == 0.5

    @pytest.mark.asyncio
    async def test_custom_result(self) -> None:
        custom = ExecutionResult(exit_code=42, stdout="", stderr="fail", duration=0.1)
        rt = MockRuntime(result=custom)
        result = await rt.run("img", ["cmd"])
        assert result.exit_code == 42
        assert result.stderr == "fail"


# ---------------------------------------------------------------------------
# WorkspaceSandbox tests (no cairn dependency)
# ---------------------------------------------------------------------------


class TestWorkspaceSandbox:
    @pytest.mark.asyncio
    async def test_exec_string_command(self, tmp_path: Path) -> None:
        """String command should be wrapped in ['sh', '-c', cmd]."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        result = await sandbox.exec("echo hello")

        assert result.exit_code == 0
        assert len(rt.calls) == 1
        assert rt.calls[0]["command"] == ["sh", "-c", "echo hello"]

    @pytest.mark.asyncio
    async def test_exec_list_command(self, tmp_path: Path) -> None:
        """List command should be passed through directly."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        await sandbox.exec(["python", "-m", "pytest"])

        assert rt.calls[0]["command"] == ["python", "-m", "pytest"]

    @pytest.mark.asyncio
    async def test_workdir_property(self, tmp_path: Path) -> None:
        """workdir returns the work_dir passed to constructor."""
        sandbox = WorkspaceSandbox(tmp_path)
        assert sandbox.workdir == tmp_path

    @pytest.mark.asyncio
    async def test_config_defaults_forwarded(self, tmp_path: Path) -> None:
        """Default SandboxConfig values should be forwarded to runtime."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        await sandbox.exec("ls")

        call = rt.calls[0]
        assert call["image"] == "remora-sandbox:latest"
        assert call["memory"] == "512m"
        assert call["cpus"] == 1.0
        assert call["network"] is False
        assert call["read_only"] is False
        assert call["timeout"] == 300.0
        assert call["workdir"] == "/workspace"
        assert call["env"] == {}

    @pytest.mark.asyncio
    async def test_custom_config_forwarded(self, tmp_path: Path) -> None:
        """Custom SandboxConfig values should be forwarded to runtime."""
        config = SandboxConfig(
            image="node:20",
            memory_limit="1g",
            cpu_limit=2.0,
            timeout=60.0,
            network=True,
            env={"NODE_ENV": "test"},
            workdir="/app",
        )
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, config=config, runtime=rt)
        await sandbox.exec("node index.js")

        call = rt.calls[0]
        assert call["image"] == "node:20"
        assert call["memory"] == "1g"
        assert call["cpus"] == 2.0
        assert call["network"] is True
        assert call["env"] == {"NODE_ENV": "test"}
        assert call["workdir"] == "/app"
        assert call["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_timeout_override(self, tmp_path: Path) -> None:
        """Per-exec timeout should override config default."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        await sandbox.exec("sleep 1", timeout=10.0)

        assert rt.calls[0]["timeout"] == 10.0

    @pytest.mark.asyncio
    async def test_volume_mount(self, tmp_path: Path) -> None:
        """work_dir should be mounted to config.workdir in volumes."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        await sandbox.exec("ls")

        assert rt.calls[0]["volumes"] == {str(tmp_path): "/workspace"}

    @pytest.mark.asyncio
    async def test_volume_mount_custom_workdir(self, tmp_path: Path) -> None:
        """Custom container workdir should appear in volumes."""
        config = SandboxConfig(workdir="/code")
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, config=config, runtime=rt)
        await sandbox.exec("ls")

        assert rt.calls[0]["volumes"] == {str(tmp_path): "/code"}

    @pytest.mark.asyncio
    async def test_multiple_execs(self, tmp_path: Path) -> None:
        """Multiple exec calls should each record in runtime."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        await sandbox.exec("echo 1")
        await sandbox.exec("echo 2")
        await sandbox.exec(["python", "script.py"])

        assert len(rt.calls) == 3
        assert rt.calls[0]["command"] == ["sh", "-c", "echo 1"]
        assert rt.calls[1]["command"] == ["sh", "-c", "echo 2"]
        assert rt.calls[2]["command"] == ["python", "script.py"]

    @pytest.mark.asyncio
    async def test_exec_returns_runtime_result(self, tmp_path: Path) -> None:
        """exec() should return the ExecutionResult from the runtime."""
        custom = ExecutionResult(exit_code=1, stdout="fail", stderr="err", duration=2.5, timed_out=False)
        rt = MockRuntime(result=custom)
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        result = await sandbox.exec("bad_cmd")

        assert result.exit_code == 1
        assert result.stdout == "fail"
        assert result.stderr == "err"
        assert result.duration == 2.5
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_default_runtime_is_docker(self, tmp_path: Path) -> None:
        """When no runtime is provided, DockerRuntime should be used."""
        sandbox = WorkspaceSandbox(tmp_path)
        assert isinstance(sandbox._runtime, DockerRuntime)

    @pytest.mark.asyncio
    async def test_default_config(self, tmp_path: Path) -> None:
        """When no config is provided, default SandboxConfig should be used."""
        sandbox = WorkspaceSandbox(tmp_path)
        assert sandbox._config.image == "remora-sandbox:latest"
        assert sandbox._config.timeout == 300.0


# ---------------------------------------------------------------------------
# DockerRuntime unit tests (subprocess mocked)
# ---------------------------------------------------------------------------


class TestDockerRuntime:
    @pytest.mark.asyncio
    async def test_builds_correct_command(self) -> None:
        """Verify the docker command line is built correctly."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"output", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            result = await rt.run(
                "python:3.12-slim",
                ["python", "-c", "print(1)"],
                volumes={"/tmp/ws": "/workspace"},
                env={"X": "1"},
                memory="256m",
                cpus=0.5,
                network=False,
                read_only=False,
                timeout=10.0,
            )

            assert result.exit_code == 0
            assert result.stdout == "output"

            # Verify the command built
            call_args = mock_exec.call_args
            cmd = call_args[0]
            assert cmd[0] == "docker"
            assert "run" in cmd
            assert "--rm" in cmd
            assert "--memory" in cmd
            assert "256m" in cmd
            assert "--network" in cmd
            assert "none" in cmd
            assert "--security-opt" in cmd
            sec_idx = list(cmd).index("--security-opt")
            assert cmd[sec_idx + 1] == "no-new-privileges"
            assert "python:3.12-slim" in cmd
            assert "python" in cmd

    @pytest.mark.asyncio
    async def test_builds_volume_flags(self) -> None:
        """Volume mounts should appear as -v host:container."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run(
                "img",
                ["cmd"],
                volumes={"/host/path": "/container/path"},
            )

            cmd = mock_exec.call_args[0]
            # Find -v flag and verify mount string
            v_indices = [i for i, arg in enumerate(cmd) if arg == "-v"]
            assert len(v_indices) == 1
            assert cmd[v_indices[0] + 1] == "/host/path:/container/path"

    @pytest.mark.asyncio
    async def test_builds_env_flags(self) -> None:
        """Environment variables should appear as -e KEY=VALUE."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run(
                "img",
                ["cmd"],
                env={"FOO": "bar", "BAZ": "qux"},
            )

            cmd = mock_exec.call_args[0]
            e_indices = [i for i, arg in enumerate(cmd) if arg == "-e"]
            env_values = {cmd[i + 1] for i in e_indices}
            assert "FOO=bar" in env_values
            assert "BAZ=qux" in env_values

    @pytest.mark.asyncio
    async def test_timeout_handling(self) -> None:
        """Verify timeout kills the process."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        proc_mock.kill = MagicMock()
        proc_mock.wait = AsyncMock()
        proc_mock.returncode = -1

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            result = await rt.run("img", ["cmd"], timeout=0.001)

            assert result.timed_out is True
            assert result.exit_code == -1
            proc_mock.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_docker_not_found(self) -> None:
        """FileNotFoundError when docker binary is missing."""
        rt = DockerRuntime()

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("docker not found"),
        ):
            result = await rt.run("img", ["cmd"])
            assert result.exit_code == -1
            assert "Docker not found" in result.stderr

    @pytest.mark.asyncio
    async def test_network_enabled(self) -> None:
        """When network=True, --network none should NOT be in command."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run("img", ["cmd"], network=True)

            cmd = mock_exec.call_args[0]
            # Should not contain --network none
            for i, arg in enumerate(cmd):
                if arg == "--network":
                    assert cmd[i + 1] != "none"
                    break
            else:
                # --network not present at all — correct
                pass

    @pytest.mark.asyncio
    async def test_workdir_flag(self) -> None:
        """Container workdir should be set via --workdir flag."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run("img", ["cmd"], workdir="/custom")

            cmd = mock_exec.call_args[0]
            wd_idx = list(cmd).index("--workdir")
            assert cmd[wd_idx + 1] == "/custom"

    @pytest.mark.asyncio
    async def test_cpu_limit_flag(self) -> None:
        """CPU limit should be set via --cpus flag."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run("img", ["cmd"], cpus=2.5)

            cmd = mock_exec.call_args[0]
            cpus_idx = list(cmd).index("--cpus")
            assert cmd[cpus_idx + 1] == "2.5"

    @pytest.mark.asyncio
    async def test_duration_measured(self) -> None:
        """Result should include a non-negative duration."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"ok", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            result = await rt.run("img", ["cmd"])
            assert result.duration >= 0.0

    @pytest.mark.asyncio
    async def test_read_only_flag(self) -> None:
        """When read_only=True, --read-only should be in command."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run("img", ["cmd"], read_only=True)

            cmd = mock_exec.call_args[0]
            assert "--read-only" in cmd

    @pytest.mark.asyncio
    async def test_read_only_default_off(self) -> None:
        """By default, --read-only should NOT be in command."""
        rt = DockerRuntime()

        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"", b""))
        proc_mock.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
            await rt.run("img", ["cmd"])

            cmd = mock_exec.call_args[0]
            assert "--read-only" not in cmd


# ---------------------------------------------------------------------------
# WorkspaceSandbox read_only forwarding
# ---------------------------------------------------------------------------


class TestWorkspaceSandboxReadOnly:
    @pytest.mark.asyncio
    async def test_read_only_forwarded(self, tmp_path: Path) -> None:
        """read_only=True in config should be forwarded to runtime."""
        config = SandboxConfig(read_only=True)
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, config=config, runtime=rt)
        await sandbox.exec("ls")

        assert rt.calls[0]["read_only"] is True

    @pytest.mark.asyncio
    async def test_read_only_default_false(self, tmp_path: Path) -> None:
        """Default config should forward read_only=False."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        await sandbox.exec("ls")

        assert rt.calls[0]["read_only"] is False
