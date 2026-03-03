# Gap Refactoring Implementation — PROGRESS

## Status: IN PROGRESS — Workstream C

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

### Workstream C — Unify Discovery (Gaps #3, #4, #5) — NEXT
- [ ] Add `parse_content()` to core/discovery.py
- [ ] Create .scm query files for Python, Markdown, TOML
- [ ] Refactor ASTWatcher to delegate to `parse_content()`
- [ ] Write tests + run full suite

### Workstream E — AgentNode Completeness (Gap #11)
- [ ] Verify/wire last_trigger_event/last_completed_at
- [ ] Write test

### Workstream D — LSP Event Completeness (Gaps #12, #13)
- [ ] Add CursorFocusEvent to events.py
- [ ] Add didChange handler with debounce
- [ ] Add cursor debouncing
- [ ] Write tests

### Final
- [ ] Full test suite run — no regressions
