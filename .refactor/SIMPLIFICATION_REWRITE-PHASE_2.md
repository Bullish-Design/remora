# Phase 2 - SubscriptionRegistry

## Goal
Implement the reactive core: a persistent SubscriptionRegistry that matches events to agents. This enables push-based triggering and removes the need for inbox polling.

## Guiding principles
- Subscription matching is explicit and visible. Favor simple AND logic over complex query logic.
- Subscriptions are persisted in SQLite and reloaded on startup.
- Default subscriptions are created for every agent (direct messages + source file changes).

## Definition of done
- `subscriptions.py` exists with `SubscriptionPattern` and `SubscriptionRegistry`.
- Subscriptions are persisted in a dedicated SQLite database.
- Pattern matching behavior is covered by unit tests.

## Step-by-step implementation

### 1) Create the module skeleton
Implementation:
- Add a new file `src/remora/core/subscriptions.py`.
- Define these dataclasses:
  - `SubscriptionPattern`
  - `Subscription`
- Define a `SubscriptionRegistry` class with async methods:
  - `initialize()`
  - `register(agent_id, pattern, is_default=False)`
  - `register_defaults(agent_id, metadata)`
  - `unregister_all(agent_id)`
  - `get_matching_agents(event)`
  - `get_subscriptions(agent_id)`
- Use only standard library modules: `asyncio`, `sqlite3`, `json`, `time`, `dataclasses`, `fnmatch`.

Testing:
- Ensure the module imports: `python -c "from remora.core.subscriptions import SubscriptionRegistry"`.

### 2) Define the pattern matching rules
Implementation:
- Implement `SubscriptionPattern` fields (all optional):
  - `event_types: list[str] | None`
  - `from_agents: list[str] | None`
  - `to_agent: str | None`
  - `path_glob: str | None`
  - `tags: list[str] | None`
- Add a `matches(event)` method that returns `True` only if all provided fields match.
  - `event_types`: match against `type(event).__name__`.
  - `from_agents` and `to_agent`: match against `event.from_agent` and `event.to_agent` if they exist.
  - `path_glob`: use `fnmatch.fnmatch(event.path, path_glob)` if `event.path` exists.
  - `tags`: treat as intersection; at least one matching tag if both lists exist.
- If a field is `None`, ignore it (do not block matching).

Testing:
- Add unit tests that cover each field in isolation and a combined AND case.
- Suggested new test file: `tests/unit/test_subscriptions.py`.

### 3) Design the SQLite schema
Implementation:
- Store subscriptions in `subscriptions.db` under the swarm path (from config in Phase 1).
- Create a table `subscriptions` with columns:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `agent_id TEXT NOT NULL`
  - `pattern_json TEXT NOT NULL`
  - `is_default INTEGER NOT NULL`
  - `created_at REAL NOT NULL`
  - `updated_at REAL NOT NULL`
- Add indexes on `agent_id` and optionally `is_default`.
- Serialize patterns as JSON using `dataclasses.asdict`.

Testing:
- Add a test that registers a subscription, closes the registry, reopens it, and reads it back.

### 4) Implement registry lifecycle and persistence
Implementation:
- Use the same SQLite and async locking style as `src/remora/core/event_store.py`.
- Ensure `initialize()` is idempotent and safe to call multiple times.
- Implement `register()` to insert a new row and return the created `Subscription`.
- Implement `get_subscriptions(agent_id)` to return all persisted subscriptions for an agent.
- Implement `unregister_all(agent_id)` to delete all rows for a given agent.

Testing:
- Add a unit test for `register` and `get_subscriptions` using a temp directory.
- Verify `unregister_all` removes all rows for that agent only.

### 5) Implement default subscriptions
Implementation:
- Define a minimal metadata type to pass in (use `CSTNode` or a small `AgentMetadata` dataclass if needed).
- Implement `register_defaults(agent_id, metadata)` to create:
  - Direct message subscription: `SubscriptionPattern(to_agent=agent_id)`
  - Source file subscription: `SubscriptionPattern(event_types=["ContentChanged"], path_glob=metadata.file_path)`
- Mark these as `is_default=True` in the database.

Testing:
- Add a test that calls `register_defaults` and asserts two subscriptions are created and marked default.

### 6) Add a fast matching path
Implementation:
- In `get_matching_agents(event)`, load subscriptions for all agents and filter by `pattern.matches(event)`.
- Keep the implementation simple for now; avoid premature optimization.
- Return a deterministic order (e.g., by `agent_id` or subscription `id`) to make tests stable.

Testing:
- Add a test that registers multiple patterns for different agents and verifies only matching agents are returned.

### 7) Wire in minimal typing and exports
Implementation:
- Add `SubscriptionPattern` and `SubscriptionRegistry` to `src/remora/core/__init__.py` exports.
- Add any necessary typing hints in `src/remora/core/events.py` for new event fields used in matching.

Testing:
- Run `python -c "from remora.core import SubscriptionRegistry"`.

### 8) Document usage in the developer docs
Implementation:
- Add a short section to `README.md` or `docs/` explaining the default subscriptions and the matching logic.
- Emphasize that subscriptions replace inbox polling.

Testing:
- `rg -n "SubscriptionRegistry" README.md docs` to confirm documentation is linked correctly.

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/unit/test_subscriptions.py::test_matches_event_types` (new).
- `tests/unit/test_subscriptions.py::test_matches_from_to` (new).
- `tests/unit/test_subscriptions.py::test_matches_path_glob` (new).
- `tests/unit/test_subscriptions.py::test_matches_tags` (new).
- `tests/unit/test_subscriptions.py::test_register_and_reload` (new).
- `tests/unit/test_subscriptions.py::test_unregister_all` (new).

Smoke tests to add/update:
- `tests/integration/test_subscriptions_smoke_real.py::test_subscriptions_persist_and_match` (new) - uses real sqlite file on disk.
- `tests/integration/test_subscriptions_smoke_real.py::test_default_subscriptions_created` (new).

Example tests to add:
- `tests/unit/test_subscriptions.py::test_deterministic_ordering` (new) - ensures stable agent ordering from matches.
- `tests/integration/test_subscriptions_smoke_real.py::test_subscription_registry_survives_restart` (new) - open/close registry and verify subscriptions remain.

## Notes
- Keep this phase isolated from the EventStore changes. EventStore integration comes next.
- Match on fields that are present on events today; later phases will add more event types with routing data.
