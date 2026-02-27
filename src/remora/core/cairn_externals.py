from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cairn.runtime.external_functions import CairnExternalFunctions

from remora.utils import PathResolver


@dataclass(slots=True)
class CairnExternals:
    """Namespace for Cairn-backed Grail externals with path normalization."""

    agent_id: str
    agent_fs: Any
    stable_fs: Any
    resolver: PathResolver
    _delegate: CairnExternalFunctions = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._delegate = CairnExternalFunctions(
            agent_id=self.agent_id,
            agent_fs=self.agent_fs,
            stable_fs=self.stable_fs,
        )

    def _normalize(self, path: str) -> str:
        return self.resolver.to_workspace_path(path)

    async def read_file(self, path: str) -> str:
        return await self._delegate.read_file(self._normalize(path))

    async def write_file(self, path: str, content: str) -> bool:
        return await self._delegate.write_file(self._normalize(path), content)

    async def list_dir(self, path: str = ".") -> list[str]:
        return await self._delegate.list_dir(self._normalize(path))

    async def file_exists(self, path: str) -> bool:
        return await self._delegate.file_exists(self._normalize(path))

    async def search_files(self, pattern: str) -> list[str]:
        return await self._delegate.search_files(pattern)

    async def search_content(self, pattern: str, path: str = ".") -> list[Any]:
        return await self._delegate.search_content(pattern, self._normalize(path))

    async def submit_result(self, summary: str, changed_files: list[str]) -> bool:
        normalized = [self._normalize(path) for path in changed_files]
        return await self._delegate.submit_result(summary, normalized)

    async def log(self, message: str) -> bool:
        return await self._delegate.log(message)

    def as_externals(self) -> dict[str, Any]:
        """Build externals dict for Grail execution."""
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "file_exists": self.file_exists,
            "search_files": self.search_files,
            "search_content": self.search_content,
            "submit_result": self.submit_result,
            "log": self.log,
        }


__all__ = ["CairnExternals"]
