import asyncio
import contextlib
import shutil
from pathlib import Path


@contextlib.asynccontextmanager
async def managed_workspace(path: Path):
    """Context manager to ensure workspace directories are created and deterministically cleaned up.
    
    Args:
        path: The path to the workspace directory.
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if path.exists():
            # Use asyncio.to_thread for blocking I/O directory removal
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
