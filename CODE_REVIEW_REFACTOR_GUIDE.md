# Remora Refactoring Guide

This guide details exactly how to implement the required fixes, improvements, and refactoring identified in `CODE_REVIEW.md`. The ultimate goal is to reach maximum alignment with the new Reactive Swarm Architecture by prioritizing safety, elegance, and non-blocking I/O. 

Remember, backwards compatibility is **NOT** required. Proceed fearlessly to reshape constraints.

---

## Phase 1: Establish Async-Safe Data Access in `SubscriptionRegistry`
Currently, `SubscriptionRegistry` blocks the asyncio event loop with synchronous `sqlite3` operations in multiple methods. 

**Steps:**
1. Open `src/remora/core/subscriptions.py`.
2. Inspect methods: `initialize`, `register`, `unregister_all`, `unregister`, `get_subscriptions`, and `get_matching_agents`.
3. Wrap every `self._conn.execute(...)` call inside an `asyncio.to_thread` dispatch loop.
   - For insertions/deletions, use a nested helper (e.g., `def _exec(conn): ...`) that executes the operation and runs `conn.commit()`, then `await asyncio.to_thread(_exec, self._conn)`.
   - For selections like `cursor.fetchall()`, write a scoped `def _fetch(conn): ...` parser and await it safely in a background thread.
4. Ensure no SQLite operation runs on the main thread loop.

---

## Phase 2: Lazy Load `structured_agents` to Re-enable Tests
The test module `test_agent_runner.py` is fundamentally crippled because importing `SwarmExecutor` eagerly forces `structured_agents` to initialize.

**Steps:**
1. Open `src/remora/core/swarm_executor.py`.
2. Find the top-level block with `from structured_agents... import ...`.
3. Move these imports explicitly **inside** the methods that use them, specifically into `_run_kernel` or `run_agent`. 
   - Note: Clean up `TYPE_CHECKING` imports for signatures if type hints currently depend on those exports directly. String literals (`"Message"`) serve nicely for late-binding types.
4. Open `tests/integration/test_agent_runner.py`.
5. Remove the `pytest.skip(...)` invocation at the top. 
6. Execute the test suite to ensure the cascade/cooldown logic works under test.

---

## Phase 3: Sanitize `AgentWorkspace` API Elements
Legacy artifacts remain present in the workspace layer, violating simplification concepts. 

**Steps:**
1. Open `src/remora/core/workspace.py`.
2. Locate the methods inside `AgentWorkspace`:
   - `def accept(self)`
   - `def reject(self)`
   - `def snapshot(self)`
   - `def restore(self)`
3. Delete these methods completely. They no longer serve a purpose within a reactive architecture tracking changes via Jujutsu/Cairn.
4. Ensure that anything calling these methods (if somehow missed in a previous refactoring phase) is similarly deleted. 

---

## Phase 4: Abstract VCS Executions (`jj commit`)
Isolate the hardcoded VCS commands operating at the bottom of the execution engine.

**Steps:**
1. Create a new module: `src/remora/core/vcs.py`.
2. Inside, define a simple utility class `VCSAdapter` with a method like `async def commit(project_root: Path, message: str)`.
3. Migrate the sub-process logic to execute `jj commit -m "{message}"` out of `swarm_executor.py` into this adapter.
4. Update `SwarmExecutor._run_agent` to invoke `await VCSAdapter.commit(...)` instead of constructing the `subprocess` logic inline.

---

## Phase 5: Normalization in `SubscriptionPattern` Path Matching
Paths produced by various operating systems and triggers create disjoint slash separators affecting glob evaluation.

**Steps:**
1. Open `src/remora/core/subscriptions.py`.
2. In `SubscriptionPattern.matches(self, event)`, locate the `path_glob` check block.
3. Import `normalize_path` from `remora.utils` (if not already present).
4. Apply the normalizer to the `path` pulled from the event *before* evaluating it against the configured `self.path_glob`.
   - `normalized = normalize_path(path).as_posix()`
   - Ensure `PurePath(normalized).match(...)` is executing reliably.

---

## Final Verification
1. Run `pytest` or `uv run pytest`. Ensure `test_agent_runner.py` is actively passing rather than skipped.
2. Confirm that running the daemon triggers zero asyncio warning logs pertaining to event loop starvation. 
3. Verify that removing the legacy methods hasn't broken the Cairn bridge implementations inside tests.
