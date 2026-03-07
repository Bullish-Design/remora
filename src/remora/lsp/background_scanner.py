from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pygls.uris import from_fs_path

from remora.core.code.discovery import node_to_event
from remora.core.events.code_events import NodeRemovedEvent


class BackgroundScanner:
    """Incremental workspace scanner that updates EventStore node projections."""

    _SUPPORTED_SUFFIXES = frozenset({".py", ".md", ".toml"})

    def __init__(
        self,
        *,
        server: Any,
        parse_content: Callable[[str, str], list[Any]],
        log: logging.Logger,
        ignore_patterns: tuple[str, ...],
    ) -> None:
        self._server = server
        self._parse_content = parse_content
        self._log = log
        self._manifest_save_interval = 10
        self._scan_pause_window_seconds = 5.0
        self._scan_pause_sleep_seconds = 0.1
        self._scan_append_slow_warning_seconds = 1.5
        self._scan_append_chunk_size = 8
        self._scan_update_edges_timeout_seconds = 1.0
        self._scan_initial_delay_seconds = 0.0
        self._scan_between_files_sleep_seconds = 0.0
        self._skip_dirs = frozenset(
            p for p in ignore_patterns if "/" not in p and "*" not in p and not p.startswith("*.")
        )

    def _load_manifest(self, manifest_path: Path) -> dict[str, dict[str, int]]:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    str(path): {"mtime_ns": int(sig["mtime_ns"]), "size": int(sig["size"])}
                    for path, sig in data.items()
                    if isinstance(sig, dict) and "mtime_ns" in sig and "size" in sig
                }
        except FileNotFoundError:
            return {}
        except Exception:
            self._log.warning("BackgroundScanner: failed to load manifest %s", manifest_path, exc_info=True)
        return {}

    def _save_manifest(self, manifest_path: Path, data: dict[str, dict[str, int]]) -> None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = manifest_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        tmp_path.replace(manifest_path)

    def _iter_source_files(self, root: Path):
        """Walk root, pruning ignored directories early."""
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                if entry.name in self._skip_dirs:
                    continue
                if entry.name.startswith(".") and entry.name not in self._skip_dirs:
                    continue
                yield from self._iter_source_files(entry)
            elif entry.is_file() and entry.suffix in self._SUPPORTED_SUFFIXES:
                yield entry

    async def _pause_for_user_activity(self) -> int:
        pauses = 0
        while self._server.user_recently_active(window_seconds=self._scan_pause_window_seconds):
            pauses += 1
            await asyncio.sleep(self._scan_pause_sleep_seconds)
        return pauses

    async def run(self) -> None:
        """Walk workspace and update discovered nodes/events."""
        self._log.info("BackgroundScanner: starting")
        root = self._server.workspace.root_path
        self._log.info("BackgroundScanner: root_path=%r", root)
        if not root:
            self._log.warning("BackgroundScanner: no workspace root, skipping")
            return

        root_path = Path(root)
        if not root_path.exists():
            self._log.error("BackgroundScanner: root_path %s does not exist", root_path)
            return

        manifest_path = root_path / ".remora" / "scan-manifest.json"
        py_files = list(self._iter_source_files(root_path))
        self._log.info("BackgroundScanner: found %d files in %s", len(py_files), root)

        await asyncio.sleep(self._scan_initial_delay_seconds)

        existing_manifest = self._load_manifest(manifest_path)
        next_manifest: dict[str, dict[str, int]] = {}
        files_since_last_manifest_save = 0

        count = 0
        parsed = 0
        skipped_unchanged = 0
        scan_pauses = 0

        for fpath in py_files:
            try:
                relative = str(fpath.relative_to(root_path))
                stat = fpath.stat()
                signature = {"mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size)}
                next_manifest[relative] = signature
                if existing_manifest.get(relative) == signature:
                    skipped_unchanged += 1
                    files_since_last_manifest_save += 1
                    if files_since_last_manifest_save >= self._manifest_save_interval:
                        self._save_manifest(manifest_path, next_manifest)
                        files_since_last_manifest_save = 0
                    continue

                scan_pauses += await self._pause_for_user_activity()

                text = fpath.read_text(encoding="utf-8", errors="replace")
                uri = from_fs_path(str(fpath))
                nodes = self._parse_content(uri, text)

                if self._server.event_store:
                    old_agents = await self._server.event_store.nodes.list_nodes(file_path=uri)
                    old_ids = {a.node_id for a in old_agents}
                    new_ids = {n.node_id for n in nodes}

                    batch_events = [node_to_event(n) for n in nodes]
                    for removed_id in old_ids - new_ids:
                        batch_events.append(NodeRemovedEvent(node_id=removed_id))

                    if batch_events:
                        timed_out = False
                        for idx in range(0, len(batch_events), self._scan_append_chunk_size):
                            chunk = batch_events[idx : idx + self._scan_append_chunk_size]
                            scan_pauses += await self._pause_for_user_activity()
                            await asyncio.sleep(0)
                            append_start = time.monotonic()
                            try:
                                await self._server.event_store.batch_append("lsp", chunk)
                            except Exception:
                                self._log.warning(
                                    "BackgroundScanner: failed to batch append file=%s chunk_start=%d chunk_size=%d",
                                    fpath,
                                    idx,
                                    len(chunk),
                                    exc_info=True,
                                )
                                timed_out = True
                                break
                            append_duration_ms = (time.monotonic() - append_start) * 1000
                            if append_duration_ms > self._scan_append_slow_warning_seconds * 1000:
                                self._log.warning(
                                    "BackgroundScanner: batch_append slow file=%s chunk_start=%d chunk_size=%d duration_ms=%.1f",
                                    fpath,
                                    idx,
                                    len(chunk),
                                    append_duration_ms,
                                )
                            await asyncio.sleep(0.05)
                        if timed_out:
                            continue

                scan_pauses += await self._pause_for_user_activity()
                try:
                    await asyncio.wait_for(
                        self._server.db.update_edges(nodes),
                        timeout=self._scan_update_edges_timeout_seconds,
                    )
                except TimeoutError:
                    self._log.warning(
                        "BackgroundScanner: update_edges timeout file=%s timeout_s=%.1f",
                        fpath,
                        self._scan_update_edges_timeout_seconds,
                    )
                    continue

                count += len(nodes)
                parsed += 1
                files_since_last_manifest_save += 1
                if files_since_last_manifest_save >= self._manifest_save_interval:
                    self._save_manifest(manifest_path, next_manifest)
                    files_since_last_manifest_save = 0

                await asyncio.sleep(self._scan_between_files_sleep_seconds)
                self._log.debug("BackgroundScanner: parsed %s -> %d nodes", fpath.relative_to(root_path), len(nodes))
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log.warning("BackgroundScanner: failed to parse %s", fpath, exc_info=True)

        try:
            self._save_manifest(manifest_path, next_manifest)
        except Exception:
            self._log.warning("BackgroundScanner: failed to save manifest %s", manifest_path, exc_info=True)

        self._log.info(
            "BackgroundScanner: complete nodes=%d parsed_files=%d total_files=%d unchanged=%d pauses=%d",
            count,
            parsed,
            len(py_files),
            skipped_unchanged,
            scan_pauses,
        )
        await self._server.notify_agents_updated()


__all__ = ["BackgroundScanner"]
