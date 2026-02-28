# Phase 3 - Extend EventStore

## Goal
Turn `EventStore` into the reactive message bus by adding routing fields and integrating it with the SubscriptionRegistry. Events should trigger agents immediately through a push queue.

## Guiding principles
- EventStore is the single source of truth for messages and triggers.
- EventBus remains for UI and live updates; it does not replace SubscriptionRegistry.
- No polling. All triggers are delivered through subscription matching.

## Definition of done
- `EventStore` includes routing fields and publishes triggers.
- New event types exist for agent messaging and file changes.
- Tests cover schema changes and trigger queue behavior.

## Step-by-step implementation

### 1) Extend the events schema
Implementation:
- Update `src/remora/core/event_store.py` table definition to include routing fields:
  - `from_agent TEXT`
  - `to_agent TEXT`
  - `correlation_id TEXT`
  - `tags TEXT` (JSON array)
- Add a lightweight migration path on startup:
  - Check `PRAGMA table_info(events)` to see which columns exist.
  - If missing, `ALTER TABLE` to add the new columns.
- Keep existing indexes; add an index on `to_agent` for direct message lookup if needed.

Testing:
- Add a unit test to create an old schema, then initialize `EventStore`, and verify the columns exist.

### 2) Add routing fields to event serialization
Implementation:
- Update `_serialize_event` to include the event fields in the JSON payload as before.
- Keep routing fields in the table columns (not only in JSON) to support direct queries later.
- Define a small helper to read `from_agent`, `to_agent`, `correlation_id`, `tags` from the event object, defaulting to `None` or empty list.

Testing:
- Add a test that appends an event with routing fields and verifies row values in the DB.

### 3) Integrate SubscriptionRegistry and EventBus in EventStore
Implementation:
- Update `EventStore.__init__` to accept optional `subscriptions: SubscriptionRegistry` and `event_bus: EventBus`.
- Add an internal `asyncio.Queue` for triggers: `_trigger_queue`.
- In `append()`:
  - Insert the event into the DB.
  - If `subscriptions` is provided, call `get_matching_agents(event)`.
  - For each matching agent, push `(agent_id, event_id, event)` onto `_trigger_queue`.
  - If `event_bus` is provided, emit the event for UI listeners.
- Keep the existing `replay()` and `get_graph_ids()` behavior intact.

Testing:
- Add a unit test that registers a subscription, appends a matching event, and verifies the trigger queue yields it.
- Add a test that ensures EventBus emit is called (use a fake or stub EventBus).

### 4) Add `get_triggers()` async iterator
Implementation:
- Add `async def get_triggers(self) -> AsyncIterator[tuple[str, int, RemoraEvent]]` to `EventStore`.
- Implement it as an infinite loop reading from `_trigger_queue`.
- Ensure this works even if there are multiple consumers (document expected usage to be one runner).

Testing:
- Add a test that appends two events and confirms the iterator yields them in order.

### 5) Add new event types for routing and file changes
Implementation:
- Update `src/remora/core/events.py` with new event dataclasses (names aligned with the docs):
  - `AgentMessageEvent` (fields: `from_agent`, `to_agent`, `content`, `tags`, `timestamp`)
  - `FileSavedEvent` (fields: `path`, `timestamp`)
  - `ContentChangedEvent` (fields: `path`, `diff`, `timestamp`)
  - `ManualTriggerEvent` (fields: `agent_id`, `reason`, `timestamp`)
- Ensure these are included in the `RemoraEvent` union and `__all__`.
- Keep event fields minimal and JSON-serializable.

Testing:
- Add a unit test verifying these dataclasses are serializable via `EventStore._serialize_event`.

### 6) Update event replay to include routing fields
Implementation:
- When `replay()` yields rows, include new columns in the dict output:
  - `from_agent`, `to_agent`, `correlation_id`, `tags`
- Parse `tags` from JSON string into a list (or `None`).

Testing:
- Add a test that appends an event with tags and verifies replay returns tags as a list.

### 7) Update imports and any callers
Implementation:
- Search for `EventStore(...)` initialization in the codebase and update construction to pass `SubscriptionRegistry` and `EventBus` when available (wiring is completed in later phases).
- Update any code that assumed `append()` only accepted `(graph_id, event)` if you change the signature (keep the same signature if possible).

Testing:
- Run `python -m pytest tests/unit/test_event_store.py` and fix any failures.

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/unit/test_event_store.py::test_append_persists_routing_fields` (new).
- `tests/unit/test_event_store.py::test_replay_includes_tags` (new).
- `tests/unit/test_event_store.py::test_trigger_queue_yields_matches` (new).
- `tests/unit/test_event_store.py::test_event_bus_emit_on_append` (new using a fake EventBus).

Smoke tests to add/update:
- `tests/integration/test_event_store_smoke_real.py::test_append_emits_and_triggers` (new) - EventStore + SubscriptionRegistry + EventBus end-to-end on disk.
- `tests/integration/test_event_store_smoke_real.py::test_replay_with_routing_fields` (new).

Example tests to add:
- `tests/unit/test_event_store.py::test_migration_adds_columns` (new) - initialize with old schema then ensure columns exist.
- `tests/integration/test_event_store_smoke_real.py::test_tags_and_correlation_roundtrip` (new).

## Notes
- Do not add any polling logic. The trigger queue should be the only delivery path for reactive execution.
- Keep the event schema backward compatible during this phase to reduce migration risk.
