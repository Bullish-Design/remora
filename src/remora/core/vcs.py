"""Version control system integration.

Provides an adapter for isolating VCS interactions (like Jujutsu).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class VCSAdapter:
    """Adapter for interacting with Version Control Systems."""

    @staticmethod
    async def commit(project_root: Path, message: str) -> None:
        """Create a commit if the workspace uses a supported VCS."""
        try:
            if (project_root / ".jj").exists():
                process = await asyncio.create_subprocess_exec(
                    "jj",
                    "commit",
                    "-m",
                    message,
                    cwd=str(project_root),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await process.wait()
        except Exception as exc:  # pragma: no cover - best effort commit
            logger.warning("Failed to create JJ commit: %s", exc)
