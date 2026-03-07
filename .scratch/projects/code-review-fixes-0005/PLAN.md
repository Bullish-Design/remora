# PLAN: Code Review 0005 Fixes

## Phase 1: Critical Issues (1-6)
1. **AgentNode imports:** Remove `try/except ImportError` for `lsprotocol` in `agent_node.py` and delete bare `pass` (Issues 1 & 2).
2. **Discovery DRY:** Extract `_parse_nodes` in `discovery.py` to fix duplication between `_parse_file` and `parse_content` (Issue 3).
3. **CompanionDispatcher:** Fix `EventBus` API calls (`subscribe` and `emit`) and fix `make_on_event` closure in `dispatcher.py` (Issues 4 & 5).
4. **Proxy Import:** Update import in `__main__.py` to use canonical path `remora.core.code.discovery` (Issue 6).

## Phase 2: Architectural Concerns (7-10)
5. **Proxy Removals:** Delete the 20 proxy files in `core/` and update all imports (Issue 7).
6. **EventStore Split:** Extract `NodeStore` functionality from `event_store.py` (Issue 8).
7. **AgentRunner Split:** Refactor `agent_runner.py` to reduce god-object tendencies (Issue 9).
8. **Event Models Unification:** Merge `CoreEvent` and `LspAgentEvent` hierarchies (Issue 10).

## Phase 3: Code Quality Issues (11-22)
9. Address remaining 12 code quality issues, starting with excessive logging in `event_store.py` and nested closures in `__main__.py`.
