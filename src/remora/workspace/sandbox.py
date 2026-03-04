"""Container sandbox for isolated workspace execution.

Runs commands inside a Docker/Podman container with resource limits,
mounting a local directory as the workspace volume.

Materialization (getting workspace files onto disk) and sync-back
(writing changed files into the workspace) are the caller's concern.
This module only handles container execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SandboxConfig:
    """Configuration for a sandbox container."""

    image: str = "remora-sandbox:latest"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    timeout: float = 300.0
    network: bool = False
    read_only: bool = False
    env: dict[str, str] = field(default_factory=dict)
    workdir: str = "/workspace"


@dataclass
class ExecutionResult:
    """Result of command execution in a sandbox."""

    exit_code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False


# ---------------------------------------------------------------------------
# Container runtime abstraction
# ---------------------------------------------------------------------------


class ContainerRuntime:
    """Abstract container runtime interface.

    Subclass and override :meth:`run` to support different backends
    (Docker, Podman, etc.).
    """

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
        """Execute *command* in a container with the given constraints."""
        raise NotImplementedError


class DockerRuntime(ContainerRuntime):
    """Docker/Podman-based container runtime."""

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
        cmd = ["docker", "run", "--rm"]

        # Resource limits
        cmd.extend(["--memory", memory])
        cmd.extend(["--cpus", str(cpus)])

        # Network
        if not network:
            cmd.extend(["--network", "none"])

        # Security: prevent privilege escalation
        cmd.extend(["--security-opt", "no-new-privileges"])
        if read_only:
            cmd.append("--read-only")

        # Working directory
        cmd.extend(["--workdir", workdir])

        # Volumes
        for host_path, container_path in (volumes or {}).items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

        # Environment
        for key, value in (env or {}).items():
            cmd.extend(["-e", f"{key}={value}"])

        # Image and command
        cmd.append(image)
        cmd.extend(command)

        start = time.monotonic()
        timed_out = False

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                timed_out = True
                stdout_bytes = b""
                stderr_bytes = b"Execution timed out"

            duration = time.monotonic() - start

            return ExecutionResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                duration=duration,
                timed_out=timed_out,
            )

        except FileNotFoundError:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Docker not found. Install Docker to use sandbox.",
                duration=0.0,
            )


# ---------------------------------------------------------------------------
# WorkspaceSandbox
# ---------------------------------------------------------------------------


class WorkspaceSandbox:
    """Container sandbox for executing commands against a local directory.

    Takes a directory path and runs commands in a container with that
    directory mounted as a volume.  Does not handle materialization or
    sync — those are the caller's responsibility.

    Args:
        work_dir: Local directory to mount into the container.
        config: Sandbox configuration (defaults to SandboxConfig()).
        runtime: Container runtime to use (defaults to DockerRuntime()).
    """

    def __init__(
        self,
        work_dir: Path,
        config: SandboxConfig | None = None,
        runtime: ContainerRuntime | None = None,
    ) -> None:
        self._work_dir = work_dir
        self._config = config or SandboxConfig()
        self._runtime = runtime or DockerRuntime()

    @property
    def workdir(self) -> Path:
        """Local directory mounted into the container."""
        return self._work_dir

    async def exec(
        self,
        command: str | list[str],
        *,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """Execute a command in the sandbox container.

        Args:
            command: Shell command string or argument list.
            timeout: Override default timeout (seconds).

        Returns:
            ExecutionResult with exit_code, stdout, stderr, duration.
        """
        if isinstance(command, str):
            cmd_list = ["sh", "-c", command]
        else:
            cmd_list = list(command)

        return await self._runtime.run(
            image=self._config.image,
            command=cmd_list,
            volumes={str(self._work_dir): self._config.workdir},
            env=self._config.env,
            workdir=self._config.workdir,
            memory=self._config.memory_limit,
            cpus=self._config.cpu_limit,
            network=self._config.network,
            read_only=self._config.read_only,
            timeout=timeout or self._config.timeout,
        )


__all__ = [
    "ContainerRuntime",
    "DockerRuntime",
    "ExecutionResult",
    "SandboxConfig",
    "WorkspaceSandbox",
]
