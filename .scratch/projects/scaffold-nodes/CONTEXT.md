# CONTEXT — Scaffold Nodes

## Current State: PROJECT COMPLETE

All 8 steps of Phase 1 are done. Full test suite passes (799 passed, 1 pre-existing failure unrelated to scaffold work).

## Summary of What Was Built

### Core Mechanics
1. **ScaffoldRequestEvent** — new domain event in `src/remora/core/events.py` with `node_id`, `node_type`, `parent_id`, `intent`, `timestamp`
2. **Scaffold status in projection** — `_is_stub()` function in `src/remora/core/projections.py` detects stub/empty source_code; projection sets `status = "scaffold"` for stubs
3. **Context-enriched prompt** — `_build_prompt()` in `src/remora/core/swarm_executor.py` adds `## Scaffold Context` section with parent source, sibling info, and intent
4. **spawn_child tool** — `src/remora/core/tools/spawn_child.py` creates stubs on disk, emits `NodeDiscoveredEvent` + `ScaffoldRequestEvent`
5. **Scaffold extension** — `remora_demo/project/.remora/models/00_scaffold_initializer.py` matches stub nodes, provides scaffold system prompt and `ScaffoldRequestEvent` subscription
6. **Watcher verified** — existing watcher already produces correct source_code for stubs (no changes needed)

### Key Design Decisions
- Scaffold is `status = "scaffold"`, not a new type or field
- `_is_stub()` detection lives in projection, not watcher
- ScaffoldRequestEvent carries intent, not full context (context assembled at prompt-build time)
- Scaffold extension uses `00_` prefix for alphabetical priority over other extensions
- Extension only matches Python stubs for non-empty content; empty/whitespace content matches any file type

### Files Modified
| File | Change |
|------|--------|
| `src/remora/core/events.py` | Added `ScaffoldRequestEvent`, updated `RemoraEvent` union + `__all__` |
| `src/remora/core/__init__.py` | Added `ScaffoldRequestEvent` import + export |
| `src/remora/core/projections.py` | Added `_is_stub()`, 3 regex patterns, scaffold status in projection, CASE expression for status upsert |
| `src/remora/core/swarm_executor.py` | Added `scaffold_context` kwarg to `_build_prompt()`, scaffold context section |
| `src/remora/core/tools/spawn_child.py` | **NEW** — `SpawnChildTool` class |
| `src/remora/core/tools/__init__.py` | Added `SpawnChildTool` import + export |
| `remora_demo/project/.remora/models/00_scaffold_initializer.py` | **NEW** — scaffold extension |
| `tests/unit/test_scaffold_events.py` | **NEW** — 14 tests |
| `tests/unit/test_scaffold_projection.py` | **NEW** — 29 tests |
| `tests/unit/test_scaffold_prompt.py` | **NEW** — 11 tests |
| `tests/unit/test_spawn_child.py` | **NEW** — 14 tests |
| `tests/unit/test_scaffold_extension.py` | **NEW** — 13 tests |
| `tests/unit/test_scaffold_watcher.py` | **NEW** — 17 tests |
| `tests/unit/test_projections.py` | Changed default source_code, added 2 edge case tests |
| `tests/integration/test_scaffold_lifecycle.py` | **NEW** — 12 tests |

### Test Counts
- Scaffold-specific tests: 110 (14 + 29 + 11 + 14 + 13 + 17 + 12)
- Total test suite: 799 passed, 1 pre-existing failure

## Test Command

```bash
python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q --no-cov
```
