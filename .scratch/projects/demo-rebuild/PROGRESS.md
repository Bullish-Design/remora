# PROGRESS — Demo Rebuild

## Task Tracker

| ID | Task | Status | Notes |
|----|------|--------|-------|
| T1 | Create configlib demo project files | done | All files exist: loader.py, schema.py, merge.py, __init__.py |
| T2 | Extension configs + remora.yaml | done | .remora/models/ and remora.yaml in place |
| T14 | Enhanced MockLLMClient | done | Full implementation in remora_demo/neovim/mock_llm.py |
| T15 | Server-side ForceLayout (layout.py) | done | 17 tests pass |
| T16 | SVG element builders (svg.py) | done | 28 tests pass |
| T17 | CSS theme + transitions (css.py) | done | 13 tests pass |
| T18 | DB->Relay bridge (bridge.py) + GraphState (state.py) | done | 13 tests pass |
| T20 | View functions (shell, graph, sidebar, event_stream) | done | 24 tests pass |
| T19 | Stario app + handlers (app.py) | done | 8 passed, 2 skipped (Stario not available in 3.13) |
| T21 | Entry points + launcher | done | 11 tests pass (__main__.py + launch.sh) |
| T22 | Integration test | done | 16 tests pass (full pipeline: DB -> State -> Layout -> Views -> Bridge) |

## Milestones

- [x] Demo project files complete (T1, T2)
- [x] MockLLM complete (T14)
- [x] Graph viewer foundations complete (T15-T18)
- [x] View layer complete (T20)
- [x] Stario app factory complete (T19)
- [x] Entry points + launcher complete (T21)
- [x] Integration test passing (T22)
- [x] **ALL TASKS DONE**

## Test Summary

| Test file | Tests | Status |
|-----------|-------|--------|
| test_layout.py | 17 | passed |
| test_svg.py | 28 | passed |
| test_css.py | 13 | passed |
| test_bridge.py | 13 | passed |
| test_views.py | 24 | passed |
| test_app.py | 8 + 2 skipped | passed |
| test_entry_points.py | 11 | passed |
| test_integration_graph.py | 16 | passed |
| **Total** | **130 passed, 2 skipped** | **All green** |
