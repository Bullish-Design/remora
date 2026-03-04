"""Validation harness for workspace code quality.

Runs configurable checks (syntax, types, tests, lint) against code
in a sandboxed container.  Takes a :class:`WorkspaceSandbox` — no cairn
dependency.  Materialization is the caller's responsibility.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from remora.workspace.sandbox import (
    ContainerRuntime,
    ExecutionResult,
    SandboxConfig,
    WorkspaceSandbox,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ValidationCheck:
    """Result of a single validation check."""

    name: str
    passed: bool
    output: str
    duration: float
    error: str | None = None


@dataclass
class ValidationResult:
    """Combined result of all validation checks."""

    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def total_duration(self) -> float:
        return sum(c.duration for c in self.checks)

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        return f"{passed}/{total} checks passed in {self.total_duration:.2f}s"


# ---------------------------------------------------------------------------
# WorkspaceValidator
# ---------------------------------------------------------------------------


class WorkspaceValidator:
    """Validate code quality by running checks in a sandbox.

    Runs configurable checks against code in a container.  The sandbox
    must already be configured with the correct ``work_dir``.

    Args:
        sandbox: A :class:`WorkspaceSandbox` to run checks in.
        checks: List of check names to run (default: ``["syntax"]``).
            Available: ``syntax``, ``types``, ``tests``, ``lint``.
    """

    DEFAULT_CHECKS: list[str] = ["syntax", "types", "tests", "lint"]

    def __init__(
        self,
        sandbox: WorkspaceSandbox,
        checks: list[str] | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._checks = checks or ["syntax"]

    @classmethod
    def from_work_dir(
        cls,
        work_dir: Path,
        checks: list[str] | None = None,
        config: SandboxConfig | None = None,
        runtime: ContainerRuntime | None = None,
    ) -> WorkspaceValidator:
        """Create a validator from a directory path.

        Convenience factory that constructs a :class:`WorkspaceSandbox`
        internally.
        """
        sandbox = WorkspaceSandbox(work_dir, config=config, runtime=runtime)
        return cls(sandbox, checks=checks)

    async def validate(self) -> ValidationResult:
        """Run all configured validation checks."""
        result = ValidationResult()

        for check_name in self._checks:
            check_method = getattr(self, f"_check_{check_name}", None)
            if check_method:
                check_result = await check_method()
                result.checks.append(check_result)
            else:
                logger.warning("Unknown check: %s", check_name)

        return result

    def _result_to_check(self, name: str, exec_result: ExecutionResult) -> ValidationCheck:
        """Convert an :class:`ExecutionResult` into a :class:`ValidationCheck`."""
        return ValidationCheck(
            name=name,
            passed=exec_result.exit_code == 0,
            output=exec_result.stdout + exec_result.stderr,
            duration=exec_result.duration,
            error=exec_result.stderr if exec_result.exit_code != 0 else None,
        )

    async def _check_syntax(self) -> ValidationCheck:
        """Check Python syntax with py_compile."""
        result = await self._sandbox.exec("find . -name '*.py' -type f -exec python -m py_compile {} +")
        return self._result_to_check("syntax", result)

    async def _check_types(self) -> ValidationCheck:
        """Check types with mypy."""
        result = await self._sandbox.exec("mypy . --ignore-missing-imports")
        return self._result_to_check("types", result)

    async def _check_tests(self) -> ValidationCheck:
        """Run tests with pytest."""
        result = await self._sandbox.exec("pytest -q --tb=short")
        return self._result_to_check("tests", result)

    async def _check_lint(self) -> ValidationCheck:
        """Lint with ruff."""
        result = await self._sandbox.exec("ruff check .")
        return self._result_to_check("lint", result)


__all__ = [
    "ValidationCheck",
    "ValidationResult",
    "WorkspaceValidator",
]
