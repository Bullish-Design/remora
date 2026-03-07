"""Pytest fixtures for Remora integration tests.

This module provides fixtures for testing the reactive, subscription-driven
Agent Swarm architecture. All fixtures use real components where possible
and only mock the LLM layer.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from remora.core.config import Config
from remora.core.store.event_store import EventStore
from remora.core.events.subscriptions import SubscriptionRegistry


# ---------------------------------------------------------------------------
# Real-time test progress hooks (helps identify hangs)
# ---------------------------------------------------------------------------
_test_start_times: dict[str, float] = {}


def pytest_runtest_logstart(nodeid: str, location: tuple) -> None:
    _test_start_times[nodeid] = time.monotonic()
    print(f"\n>>> START: {nodeid}", flush=True)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call":
        elapsed = time.monotonic() - _test_start_times.get(report.nodeid, time.monotonic())
        status = "PASS" if report.passed else ("FAIL" if report.failed else "SKIP")
        print(f">>> {status}: {report.nodeid} ({elapsed:.2f}s)", flush=True)


@pytest.fixture
def sample_workspace(tmp_path: Path) -> Path:
    """Create a real mini-codebase for tests to operate on."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def hello():\n    pass\n\ndef greet(name: str) -> str:\n    return f'Hello, {name}!'\n"
    )
    (tmp_path / "src" / "utils.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
    return tmp_path


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a test configuration."""
    return Config(
        project_path=str(tmp_path),
        discovery_paths=("src/",),
        model_base_url="http://localhost:8000/v1",
        model_default="test/model",
        model_api_key="test-key",
        swarm_root=".remora",
        swarm_id="test-swarm",
        max_concurrency=4,
        max_turns=3,
        max_trigger_depth=3,
        trigger_cooldown_ms=100,
    )


@pytest.fixture
async def event_store(tmp_path: Path) -> EventStore:
    """Create an initialized EventStore backed by a temp database."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def subscription_registry(tmp_path: Path) -> SubscriptionRegistry:
    """Create an initialized SubscriptionRegistry."""
    registry = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await registry.initialize()
    yield registry
    await registry.close()


@pytest.fixture
async def configured_event_store(
    tmp_path: Path,
    subscription_registry: SubscriptionRegistry,
) -> EventStore:
    """Create an EventStore with subscriptions configured."""
    store = EventStore(tmp_path / "events.db", subscriptions=subscription_registry)
    await store.initialize()
    yield store
    await store.close()
