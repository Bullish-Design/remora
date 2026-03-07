"""Connection/retry helpers for EventStore write operations."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sqlite3
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

_T = TypeVar("_T")

LOCK_RETRY_MAX_ATTEMPTS = 10
LOCK_RETRY_BASE_SECONDS = 0.05
LOCK_RETRY_CAP_SECONDS = 1.5


def is_locked_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def retry_delay_seconds(attempt: int) -> float:
    # Jitter avoids synchronized retries across multiple writers.
    base = min(LOCK_RETRY_CAP_SECONDS, LOCK_RETRY_BASE_SECONDS * (2 ** attempt))
    return min(LOCK_RETRY_CAP_SECONDS, base * random.uniform(0.6, 1.4))


def lock_diagnostics(db_path: Path, conn: sqlite3.Connection | None) -> dict[str, Any]:
    holders: list[int] = []
    try:
        proc = subprocess.run(
            ["lsof", "-t", str(db_path)],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        )
        if proc.stdout:
            seen: set[int] = set()
            for line in proc.stdout.splitlines():
                value = line.strip()
                if not value:
                    continue
                try:
                    pid = int(value)
                except ValueError:
                    continue
                if pid in seen:
                    continue
                seen.add(pid)
                holders.append(pid)
    except (FileNotFoundError, subprocess.SubprocessError):
        holders = []

    return {
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        "db_path": str(db_path),
        "in_transaction": bool(conn and conn.in_transaction),
        "holder_pids": holders,
    }


def begin_immediate_with_recovery(
    conn: sqlite3.Connection,
    *,
    op_name: str,
    db_path: Path,
    log: logging.Logger,
) -> None:
    """Start a write transaction, recovering from stale in-transaction state."""
    if conn.in_transaction:
        log.error(
            "%s: write connection already in_transaction before BEGIN IMMEDIATE; forcing rollback; diagnostics=%s",
            op_name,
            lock_diagnostics(db_path, conn),
        )
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            log.warning(
                "%s: rollback during stale transaction recovery failed; continuing",
                op_name,
                exc_info=True,
            )
    conn.execute("BEGIN IMMEDIATE")


async def run_locked_write_with_retries(
    op_name: str,
    op: Callable[[], _T],
    *,
    lock: asyncio.Lock,
    db_path: Path,
    conn: sqlite3.Connection | None,
    log: logging.Logger,
) -> _T:
    """Run write op under the store lock with lock retries and cancel-safe completion."""
    max_attempts = LOCK_RETRY_MAX_ATTEMPTS
    for attempt in range(max_attempts):
        try:
            async with lock:
                write_task = asyncio.create_task(asyncio.to_thread(op))
                try:
                    return await asyncio.shield(write_task)
                except asyncio.CancelledError:
                    log.warning(
                        "%s: cancelled while write thread is in-flight; waiting for completion before releasing lock",
                        op_name,
                    )
                    try:
                        await write_task
                    except Exception:
                        log.warning(
                            "%s: in-flight write failed after cancellation",
                            op_name,
                            exc_info=True,
                        )
                    raise
        except sqlite3.OperationalError as exc:
            if is_locked_error(exc) and attempt < max_attempts - 1:
                delay = retry_delay_seconds(attempt)
                if attempt in (0, max_attempts - 2):
                    log.warning(
                        "%s: database locked (attempt %d/%d), retrying in %.2fs; diagnostics=%s",
                        op_name,
                        attempt + 1,
                        max_attempts,
                        delay,
                        lock_diagnostics(db_path, conn),
                    )
                else:
                    log.warning(
                        "%s: database locked (attempt %d/%d), retrying in %.2fs...",
                        op_name,
                        attempt + 1,
                        max_attempts,
                        delay,
                    )
                await asyncio.sleep(delay)
            else:
                raise

    raise RuntimeError(f"{op_name}: unreachable retry exhaustion")
