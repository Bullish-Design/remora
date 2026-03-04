# Gap Refactoring Implementation — PROGRESS

## Status: COMPLETE ✅

### Setup
- [x] Create PLAN.md
- [x] Create ASSUMPTIONS.md
- [x] Create PROGRESS.md / CONTEXT.md
- [x] Run baseline test suite (5 known failures, 6 collection errors, all others pass)

### Workstream A — Wire the Reactive Loop (Gap #10) ✅ COMPLETE
- [x] Write failing test: did_save emits FileSavedEvent + ContentChangedEvent
- [x] Add imports + event emission to documents.py
- [x] Run test, verify pass — all 4 LSP integration tests pass

### Workstream B — Unify the Runners (Gaps #6, #7, #8, #9) ✅ COMPLETE
- [x] Create `src/remora/core/tools/lsp.py` — 3 tool classes + factory (19 tests)
- [x] Create `src/remora/core/execution.py` — `execute_agent_turn()` (16 tests)
- [x] Refactor `src/remora/core/swarm_executor.py` — delegates to execution.py (~104 lines)
- [x] Refactor `src/remora/lsp/runner.py` — delegates to execution.py, removed LLMClient
- [x] Update `src/remora/lsp/__main__.py` — passes config= to AgentRunner
- [x] Rewrite `tests/unit/test_runner_loop.py` — mocks execute_agent_turn
- [x] Update `tests/unit/test_lsp_runner.py` — removed handle_response/get_agent_tools tests
- [x] Update `tests/unit/test_unified_runner.py` — removed llm= kwarg
- [x] Fix `remora_demo/neovim/mock_llm.py` — local LLMResponse/ToolCall definitions
- [x] Fix `tests/test_mock_llm.py` — imports from mock_llm
- [x] Fix `tests/unit/test_batch8_fixes.py` — removed TestDocumentQwenXMLParser
- [x] Fix `tests/unit/test_llm_config.py` — rewritten TestLspMainUsesConfig
- [x] Full test suite: 5 pre-existing failures only, zero regressions

### Workstream C — Unify Discovery (Gaps #3, #4, #5) ✅ COMPLETE
- [x] Add `parse_content()` to core/discovery.py
- [x] Refactor ASTWatcher to delegate to `parse_content()`
- [x] 7 watcher tests + 24 discovery tests passing
- [x] Full test suite: 5 pre-existing failures only, zero regressions

### Cairn v0.2.0 API Migration ✅ COMPLETE
- [x] `cairn_bridge.py` — `_open_workspace` → `open_workspace`
- [x] `state_manager.py` — reverted to direct `from cairn import AgentStateManager`
- [x] `workspace.py` — `files.delete()` → `files.remove()`, `mkdir` → no-op
- [x] `inspector.py` — `total_size` → `total_bytes`, removed `kv_count`, fixed `close()`, KV via workspace.kv
- [x] `chat_service.py` — `from cairn import Cairn` → `import cairn` with version logging

### AgentContext Pydantic Forward-Ref Fix ✅ COMPLETE
- [x] Changed `state_manager: "RemoraStateManager | None"` → `state_manager: Any = None` in agent_context.py
- [x] Removed TYPE_CHECKING guard for RemoraStateManager
- [x] Fixed 34 test failures across 5 test files

### Delete agent_state.py — Move Models to state_manager.py ✅ COMPLETE
- [x] Moved `AgentTurnState`, `AgentMemory`, `AgentExecutionMetrics` into `state_manager.py`
- [x] Updated imports in `core/__init__.py` and `tests/unit/test_state_manager.py`
- [x] Deleted `src/remora/core/agent_state.py`
- [x] All 62 identity_unification + state_manager tests pass
- [x] Full unit test suite: only 2 known pre-existing failures (`test_event_store_append_and_replay`, `TestCLI::test_help_flag`)
- [x] Full integration tests: only 3 known pre-existing failures

### Workstream E — AgentNode Completeness (Gap #11) ✅ COMPLETE
- [x] Added domain event emission (AgentStartEvent, AgentCompleteEvent, AgentErrorEvent) to runner.py and swarm_executor.py
- [x] 6 new tests: 4 in test_runner_loop.py (TestExecuteTurnEmitsDomainEvents), 2 in test_swarm_executor.py (TestSwarmExecutorDomainEvents)
- [x] Full test suite: 5 pre-existing failures only, zero regressions

### Workstream D — LSP Event Completeness (Gaps #12, #13) ✅ COMPLETE
- [x] Add `CursorFocusEvent` to `events.py` (with `focused_agent_id` field to avoid EventStore _META_KEYS stripping)
- [x] Add `textDocument/didChange` handler in `documents.py` with 500ms debounced reparse
- [x] Add debounce infrastructure to `server.py`: `schedule_reparse()`, `_do_reparse()`, `schedule_cursor_update()`, `_do_cursor_update()`
- [x] Refactor `on_cursor_moved` in `notifications.py` to use `schedule_cursor_update()`
- [x] 21 new tests in `test_lsp_event_completeness.py` — all passing
- [x] Updated `test_lsp_notifications.py` to assert `schedule_cursor_update` instead of direct DB writes
- [x] Updated `test_lsp_integration.py` — added `textDocument/didChange` to expected features
- [x] Fixed `emit_error` in `runner.py` to use `self.server.emit_event()` instead of module-level function
- [x] Fixed `test_runner_loop.py` and `test_unified_runner.py` mock setups for `emit_event`
- [x] Full test suite: 4 pre-existing failures only, zero regressions

### Final ✅ COMPLETE
- [x] Full test suite run — 4 known pre-existing failures, zero regressions
- [x] All 5 workstreams (A, B, C, D, E) complete
- [x] All ancillary fixes (Cairn migration, AgentContext, agent_state deletion) complete
