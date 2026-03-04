# Gap Refactoring Implementation — PLAN

> **ABSOLUTE RULE: NO SUBAGENTS.** Do all work directly. No Task tool. No exceptions.

## Overview

Implement all 5 workstreams from `GAP_REFACTORING_PLAN.md` to close all 13 gaps identified in the gap analysis.

## Workstream Order

```
A → B → C → E → D
```

## Tasks

### Workstream A — Wire the Reactive Loop (Gap #10)
1. Write failing test: `did_save` emits `FileSavedEvent` + `ContentChangedEvent`
2. Add imports to `documents.py`
3. Add event emission to `did_save` handler
4. Run test, verify pass

### Workstream B — Unify the Runners (Gaps #6, #7, #8, #9)
1. Create `src/remora/core/execution.py` with `execute_agent_turn()`
2. Extract shared logic from `SwarmExecutor.run_agent()`
3. Create LSP tool classes in `src/remora/core/tools/lsp.py`
4. Refactor `SwarmExecutor.run_agent()` to delegate to `execute_agent_turn()`
5. Refactor `AgentRunner.execute_turn()` to delegate to `execute_agent_turn()`
6. Remove dead code from `runner.py` (LLMClient, LLMResponse, ToolCall, handle_response, etc.)
7. Write tests for `execute_agent_turn()`
8. Run full test suite, fix regressions

### Workstream C — Unify Discovery (Gaps #3, #4, #5)
1. Add `parse_content()` public function to `core/discovery.py`
2. Create `.scm` query files for Python, Markdown, TOML
3. Refactor `ASTWatcher.parse_and_inject_ids()` to delegate to `parse_content()`
4. Write tests for `parse_content()` and unified `ASTWatcher`
5. Run full test suite, fix regressions

### Workstream E — AgentNode Completeness (Gap #11)
1. Verify `last_trigger_event`/`last_completed_at` fields exist on AgentNode
2. Verify columns exist in nodes table schema
3. Wire population in runner
4. Write test

### Workstream D — LSP Event Completeness (Gaps #12, #13)
1. Add `CursorFocusEvent` to `events.py`
2. Add `didChange` handler with debounce
3. Add cursor debouncing to `on_cursor_moved`
4. Write tests

## Acceptance Criteria

- All 13 gaps closed
- All existing tests pass (except known pre-existing failures)
- New tests for all new functionality
- TDD: write failing test first, then implement

> **ABSOLUTE RULE: NO SUBAGENTS.** Do all work directly. No Task tool. No exceptions.
