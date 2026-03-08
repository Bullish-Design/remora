from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from remora.companion.config import CompanionConfig
from remora.companion.startup import start_companion


@pytest.mark.asyncio
async def test_start_companion_keeps_running_when_indexing_init_fails() -> None:
    event_store = MagicMock()
    event_bus = MagicMock()
    cairn_service = MagicMock()
    config = CompanionConfig(auto_index=True)

    class _FailingIndexingService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self) -> None:
            raise RuntimeError("indexing init failed")

        async def index_directory(self, *_args, **_kwargs) -> None:
            return None

    scheduled_tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task

    def _capture_create_task(coro):
        task = original_create_task(coro)
        scheduled_tasks.append(task)
        return task

    with (
        patch("remora.companion.indexing_service.IndexingService", _FailingIndexingService),
        patch("asyncio.create_task", _capture_create_task),
    ):
        registry = await start_companion(
            event_store=event_store,
            event_bus=event_bus,
            cairn_service=cairn_service,
            config=config,
        )
        await asyncio.gather(*scheduled_tasks, return_exceptions=True)

    assert registry is not None
    assert registry._router is not None
    assert event_bus.subscribe.call_count >= 1
