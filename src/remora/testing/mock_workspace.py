"""Mock workspace and KV store for unit testing.

Provides in-memory implementations of WorkspaceProtocol and KVStoreProtocol
for testing without Cairn dependencies.
"""

from __future__ import annotations

from typing import Any


class MockWorkspace:
    """In-memory workspace for unit testing.

    Implements WorkspaceProtocol without Cairn dependency.

    Example:
        ```python
        workspace = MockWorkspace({
            "/src/main.py": "print('hello')",
            "/README.md": "# Project",
        })
        content = await workspace.read("/src/main.py")
        ```
    """

    def __init__(self, files: dict[str, str | bytes] | None = None) -> None:
        """Initialize mock workspace.

        Args:
            files: Initial file contents (path -> content)
        """
        self._files: dict[str, str | bytes] = {}
        self._dirs: set[str] = {"/"}

        # Normalize paths and create parent dirs for initial files
        for path, content in (files or {}).items():
            normalized = self._normalize(path)
            self._files[normalized] = content
            self._ensure_parent_dirs(normalized)

    async def read(self, path: str) -> str:
        """Read file contents as text."""
        path = self._normalize(path)
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        content = self._files[path]
        return content if isinstance(content, str) else content.decode("utf-8")

    async def read_bytes(self, path: str) -> bytes:
        """Read file contents as bytes."""
        path = self._normalize(path)
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        content = self._files[path]
        return content if isinstance(content, bytes) else content.encode("utf-8")

    async def write(self, path: str, content: str | bytes) -> None:
        """Write file contents."""
        path = self._normalize(path)
        self._ensure_parent_dirs(path)
        self._files[path] = content

    async def exists(self, path: str) -> bool:
        """Check if file or directory exists."""
        path = self._normalize(path)
        return path in self._files or path in self._dirs

    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries."""
        path = self._normalize(path)
        if not path.endswith("/"):
            path += "/"

        entries: set[str] = set()
        # Check files
        for file_path in self._files:
            if file_path.startswith(path):
                remainder = file_path[len(path) :]
                if "/" in remainder:
                    entries.add(remainder.split("/")[0])
                elif remainder:
                    entries.add(remainder)

        # Check subdirectories
        for dir_path in self._dirs:
            if dir_path.startswith(path) and dir_path != path.rstrip("/"):
                remainder = dir_path[len(path) :]
                if remainder:
                    entries.add(remainder.split("/")[0])

        return sorted(entries)

    async def delete(self, path: str) -> None:
        """Delete a file or empty directory."""
        path = self._normalize(path)
        if path in self._files:
            del self._files[path]
        elif path in self._dirs:
            self._dirs.discard(path)

    async def mkdir(self, path: str) -> None:
        """Create directory (and parents)."""
        path = self._normalize(path)
        self._dirs.add(path)
        self._ensure_parent_dirs(path)

    def _normalize(self, path: str) -> str:
        """Normalize path to absolute workspace path."""
        if not path.startswith("/"):
            path = "/" + path
        # Remove trailing slash unless root
        return path.rstrip("/") if path != "/" else path

    def _ensure_parent_dirs(self, path: str) -> None:
        """Create all parent directories for a path."""
        parts = path.split("/")
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i]) or "/"
            self._dirs.add(parent)

    # Convenience properties for testing

    @property
    def files(self) -> dict[str, str | bytes]:
        """Access internal file storage (for test assertions)."""
        return self._files

    @property
    def dirs(self) -> set[str]:
        """Access internal directory set (for test assertions)."""
        return self._dirs


class MockKVStore:
    """In-memory KV store for unit testing.

    Implements KVStoreProtocol without Cairn dependency.

    Example:
        ```python
        kv = MockKVStore({"key1": "value1"})
        value = await kv.get("key1")
        await kv.set("key2", {"nested": "data"})
        ```
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        """Initialize mock KV store.

        Args:
            data: Initial key-value data
        """
        self._data: dict[str, Any] = dict(data or {})

    async def get(self, key: str, default: Any = None) -> Any:
        """Get value by key."""
        return self._data.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        """Set value by key."""
        self._data[key] = value

    async def delete(self, key: str) -> bool:
        """Delete key, return True if existed."""
        if key in self._data:
            del self._data[key]
            return True
        return False

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self._data

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List keys with optional prefix filter."""
        return [k for k in sorted(self._data.keys()) if k.startswith(prefix)]

    # Convenience properties for testing

    @property
    def data(self) -> dict[str, Any]:
        """Access internal data storage (for test assertions)."""
        return self._data


__all__ = ["MockWorkspace", "MockKVStore"]
