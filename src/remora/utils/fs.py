import asyncio
import contextlib
import shutil
from pathlib import Path


@contextlib.asynccontextmanager
async def managed_workspace(path: Path, *, cleanup: bool = True):
    """Context manager to ensure workspace directories are created and deterministically cleaned up.

    Args:
        path: The path to the workspace directory.
        cleanup: Whether to remove the workspace on exit.
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if cleanup and path.exists():
            # Use asyncio.to_thread for blocking I/O directory removal
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
