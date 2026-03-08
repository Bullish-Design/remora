from __future__ import annotations

from unittest.mock import MagicMock

from remora.core.store.event_store import EventStore


def test_rebind_runtime_primitives_rebuilds_asyncio_state(tmp_path) -> None:
    store = EventStore(tmp_path / "events.db")
    store.set_subscriptions(MagicMock())
    store._conn = MagicMock()
    store._node_store = MagicMock()

    old_lock = store._lock
    old_read_lock = store._read_lock
    old_trigger_queue = store._trigger_queue

    store.rebind_runtime_primitives()

    assert store._lock is not old_lock
    assert store._read_lock is not old_read_lock
    assert store._trigger_queue is not old_trigger_queue
    assert store._trigger_queue is not None

    store._node_store.bind_read_lock.assert_called_once_with(store._read_lock)
    store._node_store.bind_write_backend.assert_called_once_with(store._conn, store._lock)
