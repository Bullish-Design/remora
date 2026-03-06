"""Run an offline Remora scan for a repository.

This script runs the same core parse + EventStore projection flow as the LSP
background scan, but as a standalone job suitable for overnight downtime runs.
It writes incremental scan manifest updates and a lock/status file.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pygls.uris import from_fs_path
from tqdm import tqdm

from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent
from remora.core.projections import NodeProjection
from remora.lsp.db import RemoraDB
from remora.core.discovery import parse_content, _assign_semantic_identity

_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".devenv",
        ".git",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".nox",
        "dist",
        "build",
        ".eggs",
    }
)

_SUPPORTED_SUFFIXES = frozenset({".py", ".md", ".toml"})
_LOG = logging.getLogger("remora.scan_repo")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an offline Remora repository scan.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to scan (default: current working directory).",
    )
    parser.add_argument(
        "--manifest-save-interval",
        type=int,
        default=10,
        help="Persist manifest every N processed files (default: 10).",
    )
    parser.add_argument(
        "--append-chunk-size",
        type=int,
        default=8,
        help="Chunk size for EventStore batch_append calls (default: 8).",
    )
    parser.add_argument(
        "--graph-id",
        default="lsp",
        help="Graph ID used for event appends (default: lsp).",
    )
    parser.add_argument(
        "--events-db",
        type=Path,
        default=None,
        help="EventStore DB path (default: <root>/.remora/events/events.db).",
    )
    parser.add_argument(
        "--indexer-db",
        type=Path,
        default=None,
        help="Indexer DB path for edges (default: <root>/.remora/indexer.db).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Manifest path (default: <root>/.remora/scan-manifest.json).",
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=None,
        help="Lock/status file path (default: <root>/.remora/scan-manifest.lock).",
    )
    parser.add_argument(
        "--checkpoint-wal",
        action="store_true",
        help="Run WAL checkpoint(TRUNCATE) at the end.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level for scan diagnostics (default: INFO).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Log output file (default: <root>/.remora/logs/scan-repo-<timestamp>.log).",
    )
    parser.add_argument(
        "--slow-operation-seconds",
        type=float,
        default=1.5,
        help="Warn when a single operation exceeds this duration (default: 1.5).",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=1.0,
        help="Heartbeat interval for lock/log progress while awaiting long operations (default: 1.0).",
    )
    parser.add_argument(
        "--heartbeat-warning-seconds",
        type=float,
        default=5.0,
        help="Minimum elapsed time before heartbeat emits repeated wait warnings (default: 5.0).",
    )
    return parser.parse_args()


def _configure_logging(root_path: Path, requested_log_file: Path | None, level_name: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = requested_log_file or (root_path / ".remora" / "logs" / f"scan-repo-{stamp}.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, level_name.upper(), logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
    return log_path


def _iter_source_files(root: Path):
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                continue
            yield from _iter_source_files(entry)
        elif entry.is_file() and entry.suffix in _SUPPORTED_SUFFIXES:
            yield entry


def _load_manifest(manifest_path: Path) -> dict[str, dict[str, int]]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(path): {"mtime_ns": int(sig["mtime_ns"]), "size": int(sig["size"])}
        for path, sig in data.items()
        if isinstance(sig, dict) and "mtime_ns" in sig and "size" in sig
    }


def _save_manifest_atomic(manifest_path: Path, data: dict[str, dict[str, int]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    tmp_path.replace(manifest_path)


def _write_lock_file(lock_path: Path, payload: dict[str, Any]) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def _update_lock_file(lock_path: Path, payload: dict[str, Any], **updates: Any) -> None:
    payload.update(updates)
    payload["last_heartbeat_at"] = time.time()
    _write_lock_file(lock_path, payload)


async def _scan(args: argparse.Namespace) -> int:
    root_path: Path = args.root.resolve()
    manifest_path = (args.manifest or (root_path / ".remora" / "scan-manifest.json")).resolve()
    lock_path = (args.lock_file or (root_path / ".remora" / "scan-manifest.lock")).resolve()
    events_db_path = (args.events_db or (root_path / ".remora" / "events" / "events.db")).resolve()
    indexer_db_path = (args.indexer_db or (root_path / ".remora" / "indexer.db")).resolve()
    log_path = _configure_logging(root_path, args.log_file, args.log_level)

    started_at = time.time()
    lock_payload: dict[str, Any] = {
        "status": "running",
        "pid": os.getpid(),
        "root": str(root_path),
        "manifest_path": str(manifest_path),
        "events_db_path": str(events_db_path),
        "indexer_db_path": str(indexer_db_path),
        "started_at": started_at,
        "phase": "startup",
        "log_path": str(log_path),
    }
    _update_lock_file(lock_path, lock_payload)
    _LOG.info(
        "scan start root=%s manifest=%s events_db=%s indexer_db=%s lock=%s log=%s",
        root_path,
        manifest_path,
        events_db_path,
        indexer_db_path,
        lock_path,
        log_path,
    )

    if not root_path.exists():
        raise FileNotFoundError(f"root path does not exist: {root_path}")

    discover_start = time.monotonic()
    _LOG.info("discovering source files...")
    source_files = list(_iter_source_files(root_path))
    discover_ms = (time.monotonic() - discover_start) * 1000
    _LOG.info("discovered %d source files in %.1fms", len(source_files), discover_ms)
    _update_lock_file(lock_path, lock_payload, phase="file_discovery_complete", total_files=len(source_files))

    existing_manifest = _load_manifest(manifest_path)
    _LOG.info("loaded existing manifest entries=%d", len(existing_manifest))
    next_manifest: dict[str, dict[str, int]] = {}

    projection = NodeProjection()
    event_store = EventStore(events_db_path, projection=projection)
    db = RemoraDB(str(indexer_db_path))
    _update_lock_file(lock_path, lock_payload, phase="event_store_initialize")
    init_start = time.monotonic()
    _LOG.info("initializing EventStore...")
    await event_store.initialize()
    _LOG.info("EventStore initialized in %.1fms", (time.monotonic() - init_start) * 1000)

    parsed = 0
    skipped_unchanged = 0
    total_nodes = 0
    emitted_events = 0
    failed_files = 0
    files_since_manifest_save = 0

    repo_bar = tqdm(total=len(source_files), desc="Repository", unit="file", position=0)
    file_bar = tqdm(total=1, desc="File", unit="event", leave=False, position=1)
    heartbeat_counter = 0
    wait_state: dict[str, Any] = {
        "phase": "idle",
        "current_file": "",
        "chunk_index": None,
        "chunk_total": None,
        "op_started_monotonic": None,
        "last_wait_warning_monotonic": None,
    }

    def _begin_wait(
        phase: str,
        *,
        current_file: str,
        chunk_index: int | None = None,
        chunk_total: int | None = None,
    ) -> None:
        wait_state["phase"] = phase
        wait_state["current_file"] = current_file
        wait_state["chunk_index"] = chunk_index
        wait_state["chunk_total"] = chunk_total
        wait_state["op_started_monotonic"] = time.monotonic()
        wait_state["last_wait_warning_monotonic"] = None

    def _end_wait() -> None:
        wait_state["phase"] = "idle"
        wait_state["current_file"] = ""
        wait_state["chunk_index"] = None
        wait_state["chunk_total"] = None
        wait_state["op_started_monotonic"] = None
        wait_state["last_wait_warning_monotonic"] = None

    heartbeat_stop = asyncio.Event()

    async def _heartbeat() -> None:
        nonlocal heartbeat_counter
        while not heartbeat_stop.is_set():
            await asyncio.sleep(args.heartbeat_seconds)
            heartbeat_counter += 1
            op_started = wait_state.get("op_started_monotonic")
            elapsed = None
            if op_started is not None:
                elapsed = round(time.monotonic() - op_started, 3)
            _update_lock_file(
                lock_path,
                lock_payload,
                heartbeat_count=heartbeat_counter,
                wait_phase=wait_state["phase"],
                wait_file=wait_state["current_file"],
                wait_chunk_index=wait_state["chunk_index"],
                wait_chunk_total=wait_state["chunk_total"],
                wait_elapsed_seconds=elapsed,
            )
            if elapsed is None:
                continue
            if elapsed < args.heartbeat_warning_seconds:
                continue
            now = time.monotonic()
            last_warning = wait_state.get("last_wait_warning_monotonic")
            if last_warning is None or (now - last_warning) >= args.heartbeat_warning_seconds:
                wait_state["last_wait_warning_monotonic"] = now
                diagnostics = None
                if wait_state["phase"] == "batch_append":
                    try:
                        diagnostics = event_store._lock_diagnostics()  # noqa: SLF001
                    except Exception:
                        diagnostics = None
                _LOG.warning(
                    "heartbeat waiting phase=%s file=%s chunk=%s/%s elapsed_s=%.3f diagnostics=%s",
                    wait_state["phase"],
                    wait_state["current_file"],
                    wait_state["chunk_index"],
                    wait_state["chunk_total"],
                    elapsed,
                    diagnostics,
                )

    heartbeat_task = asyncio.create_task(_heartbeat())

    def _save_manifest_with_logs(phase: str) -> None:
        save_start = time.monotonic()
        _update_lock_file(lock_path, lock_payload, phase=phase, manifest_entries=len(next_manifest))
        _LOG.info("manifest save start phase=%s entries=%d", phase, len(next_manifest))
        _save_manifest_atomic(manifest_path, next_manifest)
        save_ms = (time.monotonic() - save_start) * 1000
        _LOG.info("manifest save end phase=%s duration_ms=%.1f entries=%d", phase, save_ms, len(next_manifest))

    try:
        for file_idx, fpath in enumerate(source_files, start=1):
            relative = str(fpath.relative_to(root_path))
            file_bar.set_description_str(f"File {relative[:80]}")
            _update_lock_file(
                lock_path,
                lock_payload,
                phase="file_start",
                current_file=relative,
                current_file_index=file_idx,
            )
            _LOG.info("file start %d/%d path=%s", file_idx, len(source_files), relative)
            try:
                stat = fpath.stat()
                signature = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
                next_manifest[relative] = signature

                if existing_manifest.get(relative) == signature:
                    skipped_unchanged += 1
                    _LOG.info("file skip unchanged path=%s mtime_ns=%d size=%d", relative, signature["mtime_ns"], signature["size"])
                    files_since_manifest_save += 1
                    if files_since_manifest_save >= args.manifest_save_interval:
                        _save_manifest_with_logs("manifest_interval_save_skip")
                        files_since_manifest_save = 0
                    file_bar.reset(total=1)
                    file_bar.update(1)
                    repo_bar.update(1)
                    continue

                read_start = time.monotonic()
                text = fpath.read_text(encoding="utf-8", errors="replace")
                _LOG.info(
                    "file read complete path=%s chars=%d duration_ms=%.1f",
                    relative,
                    len(text),
                    (time.monotonic() - read_start) * 1000,
                )
                uri = from_fs_path(str(fpath))

                list_nodes_start = time.monotonic()
                _update_lock_file(lock_path, lock_payload, phase="list_nodes", current_file=relative)
                _LOG.info("list_nodes start file=%s", relative)
                _begin_wait("list_nodes", current_file=relative)
                existing = await event_store.list_nodes(file_path=uri)
                _end_wait()
                _LOG.info(
                    "list_nodes end file=%s count=%d duration_ms=%.1f",
                    relative,
                    len(existing),
                    (time.monotonic() - list_nodes_start) * 1000,
                )
                old_nodes = [
                    {
                        "node_id": n.node_id,
                        "name": n.name,
                        "node_type": n.node_type,
                        "start_line": n.start_line,
                        "end_line": n.end_line,
                        "source_hash": n.source_hash,
                    }
                    for n in existing
                ]

                parse_start = time.monotonic()
                _update_lock_file(lock_path, lock_payload, phase="parse_nodes", current_file=relative)
                _LOG.info("parse start file=%s", relative)
                cst_nodes = parse_content(uri, text)
                _assign_semantic_identity(cst_nodes, old_nodes)
                nodes = cst_nodes
                _LOG.info(
                    "parse end file=%s nodes=%d duration_ms=%.1f",
                    relative,
                    len(nodes),
                    (time.monotonic() - parse_start) * 1000,
                )

                old_ids = {n["node_id"] for n in old_nodes}
                new_ids = {n.node_id for n in nodes}
                batch_events: list[NodeDiscoveredEvent | NodeRemovedEvent] = []
                for node in nodes:
                    batch_events.append(NodeDiscoveredEvent.from_cst_node(node))
                removed_ids = old_ids - new_ids
                for removed_id in removed_ids:
                    batch_events.append(NodeRemovedEvent(node_id=removed_id, file_path=uri))
                _LOG.info(
                    "events built file=%s discovered=%d removed=%d total=%d",
                    relative,
                    len(nodes),
                    len(removed_ids),
                    len(batch_events),
                )

                file_total = max(len(batch_events), 1)
                file_bar.reset(total=file_total)
                if batch_events:
                    total_chunks = (len(batch_events) + args.append_chunk_size - 1) // args.append_chunk_size
                    for chunk_idx, idx in enumerate(range(0, len(batch_events), args.append_chunk_size), start=1):
                        chunk = batch_events[idx : idx + args.append_chunk_size]
                        _update_lock_file(
                            lock_path,
                            lock_payload,
                            phase="batch_append",
                            current_file=relative,
                            chunk_index=chunk_idx,
                            chunk_total=total_chunks,
                            chunk_start=idx,
                            chunk_size=len(chunk),
                        )
                        _LOG.info(
                            "batch_append start file=%s chunk=%d/%d chunk_start=%d chunk_size=%d",
                            relative,
                            chunk_idx,
                            total_chunks,
                            idx,
                            len(chunk),
                        )
                        append_start = time.monotonic()
                        _begin_wait(
                            "batch_append",
                            current_file=relative,
                            chunk_index=chunk_idx,
                            chunk_total=total_chunks,
                        )
                        await event_store.batch_append(args.graph_id, chunk)
                        _end_wait()
                        append_ms = (time.monotonic() - append_start) * 1000
                        if append_ms > args.slow_operation_seconds * 1000:
                            _LOG.warning(
                                "batch_append slow file=%s chunk=%d/%d chunk_size=%d duration_ms=%.1f slow_threshold_s=%.2f",
                                relative,
                                chunk_idx,
                                total_chunks,
                                len(chunk),
                                append_ms,
                                args.slow_operation_seconds,
                            )
                        else:
                            _LOG.info(
                                "batch_append end file=%s chunk=%d/%d duration_ms=%.1f",
                                relative,
                                chunk_idx,
                                total_chunks,
                                append_ms,
                            )
                        emitted_events += len(chunk)
                        file_bar.update(len(chunk))
                else:
                    file_bar.update(1)

                _update_lock_file(lock_path, lock_payload, phase="update_edges", current_file=relative, node_count=len(nodes))
                _LOG.info("update_edges start file=%s nodes=%d", relative, len(nodes))
                update_edges_start = time.monotonic()
                _begin_wait("update_edges", current_file=relative)
                await db.update_edges(nodes)
                _end_wait()
                update_edges_ms = (time.monotonic() - update_edges_start) * 1000
                if update_edges_ms > args.slow_operation_seconds * 1000:
                    _LOG.warning(
                        "update_edges slow file=%s nodes=%d duration_ms=%.1f slow_threshold_s=%.2f",
                        relative,
                        len(nodes),
                        update_edges_ms,
                        args.slow_operation_seconds,
                    )
                else:
                    _LOG.info("update_edges end file=%s duration_ms=%.1f", relative, update_edges_ms)

                parsed += 1
                total_nodes += len(nodes)
                files_since_manifest_save += 1
                if files_since_manifest_save >= args.manifest_save_interval:
                    _save_manifest_with_logs("manifest_interval_save_parsed")
                    files_since_manifest_save = 0
                _LOG.info(
                    "file complete %d/%d path=%s parsed_nodes=%d totals(parsed=%d skipped=%d failed=%d events=%d)",
                    file_idx,
                    len(source_files),
                    relative,
                    len(nodes),
                    parsed,
                    skipped_unchanged,
                    failed_files,
                    emitted_events,
                )
            except Exception as exc:
                failed_files += 1
                _update_lock_file(
                    lock_path,
                    lock_payload,
                    phase="file_error",
                    current_file=relative,
                    last_error=f"{type(exc).__name__}: {exc}",
                )
                _LOG.exception("file failed %d/%d path=%s", file_idx, len(source_files), relative)
                tqdm.write(f"[scan] failed file {relative}: {exc}")
            finally:
                repo_bar.update(1)
                repo_bar.set_postfix(
                    parsed=parsed,
                    skipped=skipped_unchanged,
                    failed=failed_files,
                    manifest=len(next_manifest),
                )

        _save_manifest_with_logs("manifest_final_save")
        if args.checkpoint_wal:
            _update_lock_file(lock_path, lock_payload, phase="checkpoint_wal")
            _LOG.info("checkpoint_wal start mode=TRUNCATE")
            checkpoint_start = time.monotonic()
            await event_store.checkpoint_wal("TRUNCATE")
            _LOG.info("checkpoint_wal end duration_ms=%.1f", (time.monotonic() - checkpoint_start) * 1000)
    except Exception as exc:
        _LOG.exception("scan fatal error: %s", exc)
        _update_lock_file(
            lock_path,
            lock_payload,
            status="failed",
            phase="fatal_error",
            finished_at=time.time(),
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        heartbeat_stop.set()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        repo_bar.close()
        file_bar.close()
        _update_lock_file(lock_path, lock_payload, phase="closing_resources")
        _LOG.info("closing resources...")
        try:
            db.close()
        except Exception:
            _LOG.exception("failed to close RemoraDB")
        try:
            close_start = time.monotonic()
            await event_store.close()
            _LOG.info("EventStore closed in %.1fms", (time.monotonic() - close_start) * 1000)
        except Exception:
            _LOG.exception("failed to close EventStore")

    finished_at = time.time()
    status = "completed" if failed_files == 0 else "completed_with_errors"
    _update_lock_file(
        lock_path,
        lock_payload,
        status=status,
        phase="complete",
        finished_at=finished_at,
        duration_seconds=round(finished_at - started_at, 3),
        total_files=len(source_files),
        manifest_entries=len(next_manifest),
        parsed_files=parsed,
        skipped_unchanged=skipped_unchanged,
        failed_files=failed_files,
        total_nodes=total_nodes,
        emitted_events=emitted_events,
    )

    _LOG.info(
        "scan complete status=%s files=%d parsed=%d skipped=%d failed=%d nodes=%d events=%d duration_s=%.3f",
        status,
        len(source_files),
        parsed,
        skipped_unchanged,
        failed_files,
        total_nodes,
        emitted_events,
        finished_at - started_at,
    )
    tqdm.write(
        "scan complete: "
        f"files={len(source_files)} parsed={parsed} skipped={skipped_unchanged} "
        f"failed={failed_files} nodes={total_nodes} events={emitted_events} "
        f"manifest={manifest_path} lock={lock_path}"
    )
    return 0 if failed_files == 0 else 1


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_scan(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
