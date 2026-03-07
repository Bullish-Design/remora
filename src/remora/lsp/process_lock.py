import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default

@dataclass(frozen=True)
class _LockOwnerMetadata:
    pid: int | None
    heartbeat_ms: int | None
    parent_pid: int | None = None

@dataclass
class _WorkspaceProcessLock:
    lock_path: Path
    pid_path: Path
    heartbeat_interval_ms: int = _env_int("REMORA_LSP_HEARTBEAT_MS", 2_000)
    stale_owner_ms: int = _env_int("REMORA_LSP_STALE_OWNER_MS", 45_000)
    owner_term_timeout_ms: int = _env_int("REMORA_LSP_OWNER_TERM_TIMEOUT_MS", 5_000)
    handle: TextIO | None = None

    def __post_init__(self) -> None:
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def _emit(self, message: str) -> None:
        print(message, file=sys.stderr)

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _try_flock(self, handle: TextIO) -> bool:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _write_owner_metadata(self) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{os.getpid()}\n{self._now_ms()}\n{os.getppid()}\n"
        tmp_path = self.pid_path.with_name(self.pid_path.name + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.pid_path)

    def _start_heartbeat(self) -> None:
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="remora-lsp-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        interval_s = max(0.05, self.heartbeat_interval_ms / 1000.0)
        while not self._heartbeat_stop.wait(interval_s):
            try:
                self._write_owner_metadata()
            except Exception:
                self._emit("remora-lsp: failed to refresh lock-owner heartbeat")

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        thread = self._heartbeat_thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._heartbeat_thread = None

    def _read_owner_metadata(self) -> _LockOwnerMetadata:
        try:
            lines = self.pid_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return _LockOwnerMetadata(pid=None, heartbeat_ms=None, parent_pid=None)

        pid: int | None = None
        heartbeat_ms: int | None = None
        parent_pid: int | None = None
        if lines:
            try:
                pid = int(lines[0].strip())
            except Exception:
                pid = None
        if len(lines) > 1:
            try:
                raw = int(lines[1].strip())
                # Backward compatibility: old format stored whole seconds.
                heartbeat_ms = raw * 1000 if raw < 10_000_000_000 else raw
            except Exception:
                heartbeat_ms = None
        if len(lines) > 2:
            try:
                parent_pid = int(lines[2].strip())
            except Exception:
                parent_pid = None
        return _LockOwnerMetadata(pid=pid, heartbeat_ms=heartbeat_ms, parent_pid=parent_pid)

    def _is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _process_matches_workspace(self, pid: int) -> bool:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", errors="ignore")
            if "remora-lsp" not in cmdline and "remora.lsp" not in cmdline:
                return False
            owner_cwd = Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
            workspace_root = self.lock_path.parent.parent.resolve()
            return owner_cwd == workspace_root
        except Exception:
            return False

    def _heartbeat_age_ms(self, owner: _LockOwnerMetadata) -> int | None:
        if owner.heartbeat_ms is None:
            return None
        return max(0, self._now_ms() - owner.heartbeat_ms)

    def _should_reclaim_stale_owner(self, owner: _LockOwnerMetadata) -> bool:
        pid = owner.pid
        if pid is None:
            return False
        if not self._is_process_alive(pid):
            return False
        if not self._process_matches_workspace(pid):
            return False
        parent_pid = owner.parent_pid
        if parent_pid is not None:
            if parent_pid <= 1:
                return True
            if not self._is_process_alive(parent_pid):
                return True
        age_ms = self._heartbeat_age_ms(owner)
        if age_ms is None:
            return True
        return age_ms > self.stale_owner_ms

    def _terminate_stale_owner(self, pid: int) -> bool:
        if pid == os.getpid():
            return False
        self._emit(f"remora-lsp: reclaiming stale lock owner (pid={pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        deadline = time.monotonic() + max(0.1, self.owner_term_timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            if not self._is_process_alive(pid):
                return True
            time.sleep(0.1)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        for _ in range(10):
            if not self._is_process_alive(pid):
                return True
            time.sleep(0.05)
        return False

    def _lock_error_message(self, owner: _LockOwnerMetadata) -> str:
        message = "Another remora-lsp instance is already active for this workspace"
        if owner.pid is None:
            return message
        age_ms = self._heartbeat_age_ms(owner)
        if not self._is_process_alive(owner.pid):
            return f"{message} (stale metadata pid={owner.pid})"
        if owner.parent_pid is not None and owner.parent_pid > 1 and not self._is_process_alive(owner.parent_pid):
            return f"{message} (pid={owner.pid}, orphaned parent pid={owner.parent_pid})"
        if owner.parent_pid is not None and owner.parent_pid <= 1:
            return f"{message} (pid={owner.pid}, orphaned parent pid={owner.parent_pid})"
        if age_ms is not None and age_ms > self.stale_owner_ms:
            return f"{message} (pid={owner.pid}, stale heartbeat age_ms={age_ms})"
        return f"{message} (pid={owner.pid})"

    def _retry_acquire_after_reclaim(self, attempts: int = 20, delay_ms: int = 50) -> TextIO | None:
        for _ in range(max(1, attempts)):
            retry = self.lock_path.open("a+", encoding="utf-8")
            if self._try_flock(retry):
                return retry
            retry.close()
            time.sleep(max(0.0, delay_ms / 1000.0))
        return None

    def acquire(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        if not self._try_flock(handle):
            handle.close()
            owner = self._read_owner_metadata()
            if self._should_reclaim_stale_owner(owner) and owner.pid is not None:
                if self._terminate_stale_owner(owner.pid):
                    retry = self._retry_acquire_after_reclaim()
                    if retry is None:
                        raise RuntimeError(self._lock_error_message(self._read_owner_metadata()))
                    handle = retry
                else:
                    raise RuntimeError(self._lock_error_message(owner))
            else:
                raise RuntimeError(self._lock_error_message(owner))

        self.handle = handle
        self._write_owner_metadata()
        self._start_heartbeat()

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        self._stop_heartbeat()
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            handle.close()
        finally:
            self.handle = None
        try:
            self.pid_path.unlink(missing_ok=True)
        except Exception:
            pass

@dataclass
class _ParentProcessWatchdog:
    process_lock: _WorkspaceProcessLock
    poll_interval_ms: int = _env_int("REMORA_LSP_PARENT_WATCHDOG_MS", 3_000)

    def __post_init__(self) -> None:
        self._parent_pid = os.getppid()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._parent_pid <= 1:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._monitor,
            name="remora-lsp-parent-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        self._thread = None

    def _is_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _monitor(self) -> None:
        interval_s = max(0.1, self.poll_interval_ms / 1000.0)
        while not self._stop.wait(interval_s):
            if self._is_alive(self._parent_pid):
                continue
            print(
                f"remora-lsp: parent process exited (pid={self._parent_pid}); shutting down",
                file=sys.stderr,
            )
            self.process_lock.release()
            os._exit(0)
