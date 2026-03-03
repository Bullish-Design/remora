"""Protocol definitions for dependency injection and testing.

Defines abstract interfaces that allow:
- Unit testing without real Cairn workspace
- Dependency injection for flexible implementations
- Clear contracts between components
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkspaceProtocol(Protocol):
    """Abstract workspace interface for file operations.

    Enables unit testing without real Cairn workspace.
    Implementations: AgentWorkspace (real), MockWorkspace (test)

    All paths should be workspace-relative (e.g., "/src/main.py").
    """

    async def read(self, path: str) -> str:
        """Read file contents as text.

        Args:
            path: Workspace-relative file path

        Returns:
            File contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        ...

    async def write(self, path: str, content: str | bytes) -> None:
        """Write file contents.

        Args:
            path: Workspace-relative file path
            content: Content to write (text or binary)
        """
        ...

    async def exists(self, path: str) -> bool:
        """Check if file or directory exists.

        Args:
            path: Workspace-relative path

        Returns:
            True if path exists
        """
        ...

    async def list_dir(self, path: str = ".") -> list[str]:
        """List directory entries.

        Args:
            path: Workspace-relative directory path

        Returns:
            List of entry names (not full paths)
        """
        ...

    async def delete(self, path: str) -> None:
        """Delete a file.

        Args:
            path: Workspace-relative file path
        """
        ...

    async def mkdir(self, path: str) -> None:
        """Create directory (and parents if needed).

        Args:
            path: Workspace-relative directory path
        """
        ...


@runtime_checkable
class KVStoreProtocol(Protocol):
    """Abstract KV store interface.

    Enables agent state persistence and testing.
    Values must be JSON-serializable.
    """

    async def get(self, key: str, default: Any = None) -> Any:
        """Get value by key.

        Args:
            key: The key to retrieve
            default: Value to return if key doesn't exist

        Returns:
            The stored value, or default if not found
        """
        ...

    async def set(self, key: str, value: Any) -> None:
        """Set value by key.

        Args:
            key: The key to store
            value: The value (must be JSON-serializable)
        """
        ...

    async def delete(self, key: str) -> bool:
        """Delete key.

        Args:
            key: The key to delete

        Returns:
            True if key existed and was deleted
        """
        ...

    async def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: The key to check

        Returns:
            True if key exists
        """
        ...

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List keys with optional prefix filter.

        Args:
            prefix: Optional prefix to filter keys

        Returns:
            List of matching key names
        """
        ...


__all__ = ["WorkspaceProtocol", "KVStoreProtocol"]
