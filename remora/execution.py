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
    agent_id: str | None = None,
    workspace_path: str | None = None,
    stable_path: str | None = None,
    node_source: str | None = None,
    node_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a .pym script in a child process.

    This function runs in a separate OS process via ProcessPoolExecutor.
    Any crash here (segfault, os._exit) only kills this worker, not Remora.
    """
    import grail
    from remora.externals import create_remora_externals
    from fsdantic import Fsdantic

    async def _execute_async() -> dict[str, Any]:
        script = grail.load(pym_path, grail_dir=grail_dir)
        check = script.check()
        if not check.valid:
            errors = [str(e) for e in (check.errors or [])]
            return {"error": True, "code": "GRAIL_CHECK", "message": "; ".join(errors)}

        externals = {}
        if agent_id and workspace_path and node_source and node_metadata:
            try:
                # Open the workspace (and stable fs as readonly view of same path for now)
                # In a full Cairn setup, stable_fs would be distinct. 
                # Here we map them both to workspace_path for simplicity in Phase 4.
                # TODO: Pass distinct stable_path if needed.
                async with (
                    Fsdantic.open(workspace_path) as agent_fs,
                    Fsdantic.open(stable_path or workspace_path, readonly=True) as stable_fs,
                ):
                    externals = create_remora_externals(
                        agent_id=agent_id,
                        node_source=node_source,
                        node_metadata=node_metadata,
                        agent_fs=agent_fs,
                        stable_fs=stable_fs,
                    )
                    try:
                        result = await script.run(inputs=inputs, limits=limits, externals=externals)
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
        
        # Fallback for tools without externals (e.g. simple logic tools)
        try:
            # We use script.run even without externals to be consistent
            result = await script.run(inputs=inputs, limits=limits)
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
        except Exception as exc:
            return {"error": True, "code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}

    try:
        return asyncio.run(_execute_async())
    except Exception as exc:
        return {"error": True, "code": "INTERNAL", "message": f"Process crash wrapper: {exc}"}


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
        agent_id: str | None = None,
        workspace_path: Path | None = None,
        stable_path: Path | None = None,
        node_source: str | None = None,
        node_metadata: dict[str, Any] | None = None,
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
                    agent_id,
                    str(workspace_path) if workspace_path else None,
                    str(stable_path) if stable_path else None,
                    node_source,
                    node_metadata,
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
