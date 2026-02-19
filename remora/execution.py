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


# ---------------------------------------------------------------------------
# Snapshot Pause/Resume (Phase 6)
# ---------------------------------------------------------------------------

import time
import uuid
from dataclasses import dataclass

from grail.snapshot import Snapshot


@dataclass
class SnapshotRecord:
    """Tracks a suspended Grail script execution.

    Stores both the live ``Snapshot`` object and a reference to the original
    ``GrailScript`` so that ``source_map`` and ``externals`` are available
    when resuming (``Snapshot.load()`` requires them).
    """

    snapshot_id: str
    pym_path: str
    agent_id: str
    tool_name: str
    created_at: float  # time.monotonic()
    snapshot: Snapshot  # Live grail Snapshot (not serialized — keeps context)
    resume_count: int = 0
    max_resumes: int = 5  # Safety cap to prevent infinite resume loops


class SnapshotManager:
    """Manages pause/resume lifecycle for Grail script executions.

    .. note::

        Snapshots run **in-process** (not in the ``ProcessPoolExecutor``)
        because they hold references to non-picklable ``GrailScript`` context
        (``source_map``, ``externals``).  This is safe because snapshot
        operations are lightweight — they only step through external-function
        call boundaries.  Grail resource limits still protect against runaway
        scripts.

    Usage flow:

    1. ``ToolDispatcher`` calls ``start_script()`` instead of ``execute()``
    2. If the script suspends at an external call, a ``SnapshotRecord`` is
       stored and a ``snapshot_id`` is returned to the model.
    3. The model calls ``resume_tool`` with the ``snapshot_id`` to continue.
    4. ``SnapshotManager.resume_script()`` advances the snapshot with the
       provided return value.
    """

    def __init__(
        self,
        max_snapshots: int = 50,
        max_resumes: int = 5,
    ) -> None:
        self._snapshots: dict[str, SnapshotRecord] = {}
        self._max_snapshots = max_snapshots
        self._max_resumes = max_resumes

    # -- public API ----------------------------------------------------------

    def start_script(
        self,
        pym_path: str,
        grail_dir: str,
        inputs: dict[str, Any],
        externals: dict[str, Any],
        limits: dict[str, Any] | None = None,
        agent_id: str = "",
        tool_name: str = "",
    ) -> dict[str, Any]:
        """Start a script that may suspend at external-function boundaries.

        Returns a result dict: completed result, error, or snapshot info.
        """
        try:
            script = grail.load(pym_path, grail_dir=grail_dir, limits=limits)
        except grail.GrailError as exc:
            return {"error": True, "code": "GRAIL", "message": str(exc)}
        except Exception as exc:
            return {"error": True, "code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}

        try:
            snapshot = script.start(inputs=inputs, externals=externals)
        except grail.GrailError as exc:
            return {"error": True, "code": "GRAIL", "message": str(exc)}
        except Exception as exc:
            return {"error": True, "code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"}

        return self._process_snapshot(snapshot, pym_path, agent_id, tool_name)

    def resume_script(
        self,
        snapshot_id: str,
        return_value: Any = None,
    ) -> dict[str, Any]:
        """Resume a previously suspended script with a return value.

        The return value is injected as the result of the external function
        call that caused the suspension.
        """
        record = self._snapshots.get(snapshot_id)
        if record is None:
            return {
                "error": True,
                "code": "SNAPSHOT_NOT_FOUND",
                "message": f"No snapshot with id '{snapshot_id}'",
            }

        if record.resume_count >= record.max_resumes:
            self._snapshots.pop(snapshot_id, None)
            return {
                "error": True,
                "code": "MAX_RESUMES",
                "message": f"Max resume count ({record.max_resumes}) exceeded",
            }

        try:
            new_snapshot = record.snapshot.resume(return_value=return_value)
        except Exception as exc:
            self._snapshots.pop(snapshot_id, None)
            return {"error": True, "code": "RESUME_FAILED", "message": str(exc)}

        record.resume_count += 1

        if new_snapshot.is_complete:
            self._snapshots.pop(snapshot_id, None)
            return {"error": False, "result": new_snapshot.value}

        # Still suspended — update the record with the new snapshot
        record.snapshot = new_snapshot
        return {
            "error": False,
            "suspended": True,
            "snapshot_id": snapshot_id,
            "function_name": new_snapshot.function_name,
            "args": list(new_snapshot.args),
            "kwargs": new_snapshot.kwargs,
            "resume_count": record.resume_count,
            "message": "Script still paused. Call resume_tool again to continue.",
        }

    def cleanup_agent(self, agent_id: str) -> int:
        """Remove all snapshots belonging to an agent. Returns count removed."""
        to_remove = [
            sid for sid, r in self._snapshots.items() if r.agent_id == agent_id
        ]
        for sid in to_remove:
            del self._snapshots[sid]
        return len(to_remove)

    def clear(self) -> None:
        """Remove all snapshots."""
        self._snapshots.clear()

    @property
    def active_count(self) -> int:
        """Number of currently stored snapshots."""
        return len(self._snapshots)

    # -- internal helpers ----------------------------------------------------

    def _process_snapshot(
        self,
        snapshot: Snapshot,
        pym_path: str,
        agent_id: str,
        tool_name: str,
    ) -> dict[str, Any]:
        """Classify a snapshot as completed or suspended."""
        if snapshot.is_complete:
            return {"error": False, "result": snapshot.value}

        # Suspended at an external function call — store for later resume
        snapshot_id = str(uuid.uuid4())
        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            pym_path=pym_path,
            agent_id=agent_id,
            tool_name=tool_name,
            created_at=time.monotonic(),
            snapshot=snapshot,
            max_resumes=self._max_resumes,
        )
        self._store(record)
        return {
            "error": False,
            "suspended": True,
            "snapshot_id": snapshot_id,
            "function_name": snapshot.function_name,
            "args": list(snapshot.args),
            "kwargs": snapshot.kwargs,
            "message": "Script paused. Call resume_tool with this snapshot_id to continue.",
        }

    def _store(self, record: SnapshotRecord) -> None:
        """Store a snapshot, evicting oldest if at capacity."""
        if len(self._snapshots) >= self._max_snapshots:
            oldest = min(self._snapshots.values(), key=lambda r: r.created_at)
            del self._snapshots[oldest.snapshot_id]
        self._snapshots[record.snapshot_id] = record
