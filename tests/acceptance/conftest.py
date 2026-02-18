"""Acceptance test configuration."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from remora.config import ServerConfig

SERVER = ServerConfig()


def _server_available() -> bool:
    """Check if vLLM server is available."""
    try:
        response = httpx.get(f"{SERVER.base_url}/models", timeout=2)
        response.raise_for_status()
        model_ids = {item["id"] for item in response.json().get("data", [])}
        return SERVER.default_adapter in model_ids
    except Exception:
        return False


def pytest_collection_modifyitems(items):
    """Skip acceptance tests if vLLM server not available."""
    if not _server_available():
        skip = pytest.mark.skip(
            reason=f"vLLM server not reachable at {SERVER.base_url} or model {SERVER.default_adapter} not loaded"
        )
        for item in items:
            if "acceptance" in item.keywords or item.get_closest_marker("acceptance"):
                item.add_marker(skip)


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a temporary copy of the sample project."""
    src = Path(__file__).parent / "sample_project"
    dst = tmp_path / "sample_project"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def remora_config(sample_project: Path) -> Path:
    """Get path to sample project remora config."""
    return sample_project / "remora.yaml"
