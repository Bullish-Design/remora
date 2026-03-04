"""Tests for remora.workspace.validation — validation harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.workspace.sandbox import (
    ContainerRuntime,
    ExecutionResult,
    SandboxConfig,
    WorkspaceSandbox,
)
from remora.workspace.validation import (
    ValidationCheck,
    ValidationResult,
    WorkspaceValidator,
)


# ---------------------------------------------------------------------------
# Mock Runtime (same pattern as test_sandbox.py)
# ---------------------------------------------------------------------------


class MockRuntime(ContainerRuntime):
    """In-memory runtime that returns configurable results per command."""

    def __init__(self, results: dict[str, ExecutionResult] | None = None) -> None:
        self.calls: list[dict] = []
        self._results = results or {}
        self._default = ExecutionResult(exit_code=0, stdout="ok\n", stderr="", duration=0.5)

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
        # Match on a substring of the command to return specific results
        cmd_str = " ".join(command)
        for pattern, result in self._results.items():
            if pattern in cmd_str:
                return result
        return self._default


# ---------------------------------------------------------------------------
# ValidationCheck tests
# ---------------------------------------------------------------------------


class TestValidationCheck:
    def test_passed_check(self) -> None:
        check = ValidationCheck(name="syntax", passed=True, output="ok", duration=1.0)
        assert check.passed is True
        assert check.error is None

    def test_failed_check(self) -> None:
        check = ValidationCheck(
            name="types",
            passed=False,
            output="errors found",
            duration=2.0,
            error="type error at line 5",
        )
        assert check.passed is False
        assert check.error == "type error at line 5"


# ---------------------------------------------------------------------------
# ValidationResult tests
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_empty_result(self) -> None:
        result = ValidationResult()
        assert result.all_passed is True
        assert result.total_duration == 0.0
        assert result.summary() == "0/0 checks passed in 0.00s"

    def test_all_passed(self) -> None:
        result = ValidationResult(
            checks=[
                ValidationCheck(name="syntax", passed=True, output="ok", duration=1.0),
                ValidationCheck(name="lint", passed=True, output="ok", duration=0.5),
            ]
        )
        assert result.all_passed is True
        assert result.total_duration == 1.5
        assert result.summary() == "2/2 checks passed in 1.50s"

    def test_some_failed(self) -> None:
        result = ValidationResult(
            checks=[
                ValidationCheck(name="syntax", passed=True, output="ok", duration=1.0),
                ValidationCheck(
                    name="types",
                    passed=False,
                    output="err",
                    duration=2.0,
                    error="fail",
                ),
            ]
        )
        assert result.all_passed is False
        assert result.total_duration == 3.0
        assert result.summary() == "1/2 checks passed in 3.00s"

    def test_all_failed(self) -> None:
        result = ValidationResult(
            checks=[
                ValidationCheck(
                    name="syntax",
                    passed=False,
                    output="err",
                    duration=1.0,
                    error="fail",
                ),
                ValidationCheck(
                    name="lint",
                    passed=False,
                    output="err",
                    duration=0.5,
                    error="fail",
                ),
            ]
        )
        assert result.all_passed is False
        assert result.summary() == "0/2 checks passed in 1.50s"


# ---------------------------------------------------------------------------
# WorkspaceValidator tests (using MockRuntime — no cairn, no Docker)
# ---------------------------------------------------------------------------


class TestWorkspaceValidator:
    @pytest.mark.asyncio
    async def test_default_runs_syntax_only(self, tmp_path: Path) -> None:
        """Default checks list should be ['syntax']."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox)

        result = await validator.validate()

        assert len(result.checks) == 1
        assert result.checks[0].name == "syntax"
        assert result.all_passed is True

    @pytest.mark.asyncio
    async def test_syntax_check_passes(self, tmp_path: Path) -> None:
        """Syntax check should pass when exit_code == 0."""
        rt = MockRuntime(results={"py_compile": ExecutionResult(exit_code=0, stdout="", stderr="", duration=0.3)})
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["syntax"])

        result = await validator.validate()

        assert result.checks[0].passed is True
        assert result.checks[0].name == "syntax"

    @pytest.mark.asyncio
    async def test_syntax_check_fails(self, tmp_path: Path) -> None:
        """Syntax check should fail when exit_code != 0."""
        rt = MockRuntime(
            results={
                "py_compile": ExecutionResult(
                    exit_code=1,
                    stdout="",
                    stderr="SyntaxError: invalid syntax",
                    duration=0.2,
                )
            }
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["syntax"])

        result = await validator.validate()

        assert result.checks[0].passed is False
        assert "SyntaxError" in (result.checks[0].error or "")

    @pytest.mark.asyncio
    async def test_types_check(self, tmp_path: Path) -> None:
        """Types check runs mypy."""
        rt = MockRuntime(
            results={"mypy": ExecutionResult(exit_code=0, stdout="Success: no issues\n", stderr="", duration=5.0)}
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["types"])

        result = await validator.validate()

        assert len(result.checks) == 1
        assert result.checks[0].name == "types"
        assert result.checks[0].passed is True
        # Verify mypy was invoked
        assert any("mypy" in " ".join(c["command"]) for c in rt.calls)

    @pytest.mark.asyncio
    async def test_tests_check(self, tmp_path: Path) -> None:
        """Tests check runs pytest."""
        rt = MockRuntime(
            results={
                "pytest": ExecutionResult(
                    exit_code=0,
                    stdout="5 passed\n",
                    stderr="",
                    duration=3.0,
                )
            }
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["tests"])

        result = await validator.validate()

        assert result.checks[0].name == "tests"
        assert result.checks[0].passed is True
        assert any("pytest" in " ".join(c["command"]) for c in rt.calls)

    @pytest.mark.asyncio
    async def test_lint_check(self, tmp_path: Path) -> None:
        """Lint check runs ruff."""
        rt = MockRuntime(
            results={
                "ruff": ExecutionResult(
                    exit_code=0,
                    stdout="All checks passed!\n",
                    stderr="",
                    duration=1.0,
                )
            }
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["lint"])

        result = await validator.validate()

        assert result.checks[0].name == "lint"
        assert result.checks[0].passed is True
        assert any("ruff" in " ".join(c["command"]) for c in rt.calls)

    @pytest.mark.asyncio
    async def test_multiple_checks(self, tmp_path: Path) -> None:
        """Multiple checks should all run in order."""
        rt = MockRuntime(
            results={
                "py_compile": ExecutionResult(exit_code=0, stdout="", stderr="", duration=0.3),
                "mypy": ExecutionResult(
                    exit_code=1,
                    stdout="",
                    stderr="Found 3 errors",
                    duration=4.0,
                ),
                "pytest": ExecutionResult(
                    exit_code=0,
                    stdout="10 passed\n",
                    stderr="",
                    duration=2.0,
                ),
                "ruff": ExecutionResult(exit_code=0, stdout="ok\n", stderr="", duration=0.5),
            }
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["syntax", "types", "tests", "lint"])

        result = await validator.validate()

        assert len(result.checks) == 4
        assert result.checks[0].name == "syntax"
        assert result.checks[0].passed is True
        assert result.checks[1].name == "types"
        assert result.checks[1].passed is False
        assert result.checks[2].name == "tests"
        assert result.checks[2].passed is True
        assert result.checks[3].name == "lint"
        assert result.checks[3].passed is True
        assert result.all_passed is False

    @pytest.mark.asyncio
    async def test_unknown_check_skipped(self, tmp_path: Path) -> None:
        """Unknown check names should be skipped with a warning."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["nonexistent"])

        result = await validator.validate()

        assert len(result.checks) == 0
        assert result.all_passed is True

    @pytest.mark.asyncio
    async def test_from_work_dir_factory(self, tmp_path: Path) -> None:
        """from_work_dir should create a validator with a sandbox."""
        rt = MockRuntime()
        validator = WorkspaceValidator.from_work_dir(tmp_path, checks=["syntax"], runtime=rt)

        result = await validator.validate()

        assert len(result.checks) == 1
        assert result.checks[0].passed is True
        # Verify the sandbox was configured with the correct work_dir
        assert rt.calls[0]["volumes"] == {str(tmp_path): "/workspace"}

    @pytest.mark.asyncio
    async def test_from_work_dir_custom_config(self, tmp_path: Path) -> None:
        """from_work_dir should forward SandboxConfig."""
        config = SandboxConfig(image="node:20", timeout=60.0)
        rt = MockRuntime()
        validator = WorkspaceValidator.from_work_dir(tmp_path, checks=["syntax"], config=config, runtime=rt)

        await validator.validate()

        assert rt.calls[0]["image"] == "node:20"
        assert rt.calls[0]["timeout"] == 60.0

    @pytest.mark.asyncio
    async def test_check_output_includes_stdout_and_stderr(self, tmp_path: Path) -> None:
        """ValidationCheck.output should contain both stdout and stderr."""
        rt = MockRuntime(
            results={
                "py_compile": ExecutionResult(
                    exit_code=1,
                    stdout="compiling...\n",
                    stderr="SyntaxError\n",
                    duration=0.2,
                )
            }
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["syntax"])

        result = await validator.validate()

        check = result.checks[0]
        assert "compiling..." in check.output
        assert "SyntaxError" in check.output

    @pytest.mark.asyncio
    async def test_check_error_none_on_success(self, tmp_path: Path) -> None:
        """ValidationCheck.error should be None when check passes."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["syntax"])

        result = await validator.validate()

        assert result.checks[0].error is None

    @pytest.mark.asyncio
    async def test_default_checks_class_attribute(self) -> None:
        """DEFAULT_CHECKS should contain the four standard checks."""
        assert WorkspaceValidator.DEFAULT_CHECKS == [
            "syntax",
            "types",
            "tests",
            "lint",
        ]

    @pytest.mark.asyncio
    async def test_all_default_checks_run(self, tmp_path: Path) -> None:
        """Running with all DEFAULT_CHECKS should produce 4 results."""
        rt = MockRuntime()
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=WorkspaceValidator.DEFAULT_CHECKS)

        result = await validator.validate()

        assert len(result.checks) == 4
        names = [c.name for c in result.checks]
        assert names == ["syntax", "types", "tests", "lint"]

    @pytest.mark.asyncio
    async def test_duration_tracked(self, tmp_path: Path) -> None:
        """Each check should report its duration from the sandbox result."""
        rt = MockRuntime(
            results={
                "py_compile": ExecutionResult(exit_code=0, stdout="", stderr="", duration=1.23),
                "ruff": ExecutionResult(exit_code=0, stdout="", stderr="", duration=4.56),
            }
        )
        sandbox = WorkspaceSandbox(tmp_path, runtime=rt)
        validator = WorkspaceValidator(sandbox, checks=["syntax", "lint"])

        result = await validator.validate()

        assert result.checks[0].duration == 1.23
        assert result.checks[1].duration == 4.56
        assert result.total_duration == pytest.approx(5.79)
