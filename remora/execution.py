"""Process-isolated Grail script execution."""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path
from typing import Any

import grail
import grail.limits


def _run_in_child(
    pym_path: str,
    grail_dir: str,
    inputs: dict[str, Any],
    limits: dict[str, Any],
) -> dict[str, Any]:
    """Execute a .pym script in a child process.

    This function runs in a separate OS process via ProcessPoolExecutor.
    Any crash here (segfault, os._exit) only kills this worker, not Remora.
    """
    script = grail.load(pym_path, grail_dir=grail_dir)
    check = script.check()
    if not check.valid:
        errors = [str(e) for e in (check.errors or [])]
        return {"error": True, "code": "GRAIL_CHECK", "message": "; ".join(errors)}
    try:
        result = script.run_sync(inputs=inputs, limits=limits)
        return {"error": False, "result": result}
    except grail.LimitError as exc:
        return {
            "error": True,
            "code": "LIMIT",
            "message": str(exc),
            "limit_type": getattr(exc, "limit_type", None),
        }
    except grail.ExecutionError as exc:
        return {
            "error": True,
            "code": "EXECUTION",
            "message": str(exc),
            "lineno": getattr(exc, "lineno", None),
        }
    except grail.GrailError as exc:
        return {"error": True, "code": "GRAIL", "message": str(exc)}
    except Exception as exc:
        return {"error": True, "code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}


class ProcessIsolatedExecutor:
    """Run Grail scripts in isolated child processes."""

    def __init__(self, max_workers: int = 4, call_timeout: float = 300.0) -> None:
        self._max_workers = max_workers
        self._call_timeout = call_timeout
        self._pool: concurrent.futures.ProcessPoolExecutor | None = None

    def _ensure_pool(self) -> concurrent.futures.ProcessPoolExecutor:
        if self._pool is None or self._pool._broken:  # noqa: SLF001
            self._pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=self._max_workers
            )
        return self._pool

    async def execute(
        self,
        pym_path: Path,
        grail_dir: Path,
        inputs: dict[str, Any],
        limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a .pym script in an isolated child process.

        Args:
            pym_path: Path to the .pym script file.
            grail_dir: Grail artifacts directory.
            inputs: Input dict to pass to the script.
            limits: Grail resource limits (defaults to grail.limits.DEFAULT).

        Returns:
            Structured result dict with ``error`` key indicating success/failure.
        """
        resolved_limits = limits or grail.limits.DEFAULT
        loop = asyncio.get_running_loop()
        pool = self._ensure_pool()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    pool,
                    _run_in_child,
                    str(pym_path),
                    str(grail_dir),
                    inputs,
                    resolved_limits,
                ),
                timeout=self._call_timeout,
            )
        except concurrent.futures.BrokenExecutor:
            self._pool = None  # Force pool recreation on next call
            return {
                "error": True,
                "code": "PROCESS_CRASH",
                "message": "Script execution process crashed unexpectedly",
            }
        except asyncio.TimeoutError:
            return {
                "error": True,
                "code": "TIMEOUT",
                "message": f"Script execution timed out after {self._call_timeout}s",
            }

    async def shutdown(self) -> None:
        """Shut down the process pool."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
