# Phase 4 - Agent State and Swarm Registry

## Goal
Persist agent identity and state on disk and create a registry for all agents (swarm state). This enables startup reconciliation and stable agent identities.

## Guiding principles
- Each agent is represented by a workspace directory containing `workspace.db` and `state.jsonl`.
- The swarm registry is authoritative for all known agents (SQLite).
- No `last_seen_event_id` tracking; events are pushed.

## Definition of done
- `AgentState` exists with load/save helpers.
- `SwarmState` registry exists and can upsert and list agents.
- `reconciler.py` performs startup diff and registers default subscriptions.

## Step-by-step implementation

### 1) Define the AgentState format
Implementation:
- Create `src/remora/core/agent_state.py`.
- Define a `@dataclass` `AgentState` with fields:
  - `agent_id` (string)
  - `node_type` (string)
  - `file_path` (string)
  - `parent_id` (string | None)
  - `range` (tuple of start_line, end_line)
  - `connections` (dict[str, str])
  - `chat_history` (list[dict])
  - `custom_subscriptions` (list[SubscriptionPattern])
  - `last_updated` (float)
- Implement `load(path: Path) -> AgentState` and `save(path: Path) -> None` using JSON lines.
  - Keep one JSON object per line for append-only state changes if needed.
  - On load, read the last line as the current state snapshot.

Testing:
- Add a unit test that writes an AgentState to a temp file and loads it back with equivalent content.

### 2) Create the SwarmState registry
Implementation:
- Create `src/remora/core/swarm_state.py`.
- Define a `SwarmState` class that stores agent metadata in `swarm_state.db`.
- Schema should include:
  - `agent_id` (primary key)
  - `node_type`
  - `file_path`
  - `parent_id`
  - `start_line`, `end_line`
  - `status` (active, orphaned)
  - `created_at`, `updated_at`
- Provide methods:
  - `initialize()`
  - `upsert(agent_metadata)`
  - `mark_orphaned(agent_id)`
  - `list_agents()`
  - `get_agent(agent_id)`

Testing:
- Add a test that upserts a record, retrieves it, and then marks it orphaned.

### 3) Define minimal AgentMetadata to share between discovery and swarm
Implementation:
- Create a lightweight `AgentMetadata` dataclass (or reuse `CSTNode`) that includes:
  - `agent_id`, `node_type`, `file_path`, `parent_id`, `start_line`, `end_line`.
- Ensure `discovery.py` can provide this metadata without extra work.

Testing:
- Add a test that converts a `CSTNode` to `AgentMetadata` (if you add a helper).

### 4) Implement agent directory layout helpers
Implementation:
- Add helpers to `src/remora/core/workspace.py` or a new `swarm_paths.py`:
  - `get_agent_dir(swarm_root, agent_id)`
  - `get_agent_state_path(swarm_root, agent_id)`
  - `get_agent_workspace_path(swarm_root, agent_id)`
- Ensure these match the layout described in `REMORA_CST_DEMO_ANALYSIS.md`.

Testing:
- Add a unit test for these helpers to confirm deterministic paths.

### 5) Add the reconciler
Implementation:
- Create `src/remora/core/reconciler.py`.
- Implement a `reconcile_on_startup(project_path, swarm_state, subscriptions, discovery)` function:
  - Discover current CST nodes.
  - Load existing swarm_state records.
  - Diff to find new, deleted, and changed nodes.
  - For new nodes:
    - Create agent directory structure.
    - Initialize `AgentState` with identity fields.
    - Register default subscriptions.
    - Upsert into `SwarmState`.
  - For deleted nodes:
    - Mark as orphaned and remove subscriptions.
  - For changed nodes (file path or range changes):
    - Update swarm_state record.
    - Emit `ContentChangedEvent` (through EventStore in later phases).

Testing:
- Add a unit test that simulates discovery returning two nodes, then removing one, and ensures registry updates accordingly.

### 6) Update workspace/cairn integration to include state.jsonl
Implementation:
- In `src/remora/core/workspace.py` and `src/remora/core/cairn_bridge.py`, ensure agent creation also creates `state.jsonl` next to `workspace.db`.
- Do not change the workspace content semantics; just add the state file as metadata storage.

Testing:
- Add a test that creates a workspace and verifies the state file exists.

### 7) Wire minimal exports
Implementation:
- Add `AgentState`, `SwarmState`, and `reconcile_on_startup` exports to `src/remora/core/__init__.py`.
- Update any import paths in the codebase to use these new modules.

Testing:
- Run `python -c "from remora.core import AgentState, SwarmState"`.

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/unit/test_agent_state.py::test_state_round_trip` (new) - save/load JSONL state.
- `tests/unit/test_swarm_state.py::test_upsert_and_get` (new).
- `tests/unit/test_swarm_state.py::test_mark_orphaned` (new).
- `tests/unit/test_reconciler.py::test_reconcile_creates_new_agents` (new).
- `tests/unit/test_reconciler.py::test_reconcile_marks_deleted_agents` (new).

Smoke tests to add/update:
- `tests/integration/test_reconciler_smoke_real.py::test_reconcile_creates_agent_dirs` (new) - uses discovery on a temp project.
- `tests/integration/test_reconciler_smoke_real.py::test_reconcile_registers_default_subscriptions` (new).

Example tests to add:
- `tests/unit/test_reconciler.py::test_reconcile_emits_content_changed` (new).
- `tests/integration/test_reconciler_smoke_real.py::test_state_jsonl_written` (new).

## Notes
- Keep AgentState small and focused; avoid embedding live runtime objects.
- Any event emission during reconciliation should be minimal and use `ContentChangedEvent` to inform subscriptions.
