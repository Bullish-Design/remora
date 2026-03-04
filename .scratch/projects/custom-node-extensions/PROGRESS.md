# PROGRESS — Custom Node Extensions Demo

## Status: COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 1.1 | Unit tests for ClassDocGenerator (failing) | done |
| 1.2 | Implement ClassDocGenerator extension | done |
| 1.3 | Unit tests for FunctionTestScaffold (failing) | done |
| 1.4 | Implement FunctionTestScaffold extension | done |
| 1.5 | Unit tests for SwarmMonitor (failing) | done |
| 1.6 | Implement SwarmMonitor extension | done |
| 2.1 | Projection integration tests | done |
| 3.1 | Subscription pattern matching tests | done |
| 3.2 | Subscription registry routing tests | done |
| 4.1 | E2e cascade demo test | done |
| 5.1 | Full test suite verification | done |
| 5.2 | Fix stem-name bug (name="MONITOR" not "MONITOR.md") | done |
| 5.3 | Fix FunctionTool adapter (Tool.from_function bug) | done |
| 6.1 | E2E scenario: ext_discovery | done |
| 6.2 | E2E scenario: ext_multi_file | done |
| 6.3 | E2E scenario: ext_edit_cascade | done |
| 6.4 | Register scenarios + update harness | done |
| 6.5 | Run scenarios without recording | done |
| 6.6 | Run scenarios with GIF recording | done |

## Final Test Results

**713 passed, 0 xfailed, 0 failures, 2 warnings**

- Baseline was 659 passed, 2 xfailed
- 52 new tests added (42 unit + 10 integration) = 711 passed
- Fixed 2 xfailed tests (FunctionTool adapter) = 713 passed, 0 xfailed

## Bug Fixes Applied

1. **Stem-name bug**: `ASTWatcher._parse_file_only()` sets `name = Path(uri).stem`, so
   `MONITOR.md` -> `name="MONITOR"` and `__init__.py` -> `name="__init__"`. Updated
   extension configs (`swarm_monitor.py`, `package_init.py`) and all test references.

2. **FunctionTool adapter**: `build_chat_tools()` called `Tool.from_function()` which
   doesn't exist on the `Tool` Protocol. Created `FunctionTool` class in `chat.py` that
   wraps async callables into the `Tool` protocol (auto-generates `ToolSchema` from
   function signature). Removed xfail markers from `TestBuildChatTools`.

## E2E Scenarios

Three new scenarios in `e2e/scenarios/`:

| Scenario | File | Description | GIF |
|----------|------|-------------|-----|
| ext_discovery | `ext_discovery.py` | Open schema.py, browse class+function, open panel | yes |
| ext_multi_file | `ext_multi_file.py` | Navigate schema.py -> loader.py -> merge.py | yes |
| ext_edit_cascade | `ext_edit_cascade.py` | Edit SchemaError + load_config, watch extensions react | yes |

Run with: `devenv shell -- python -m e2e.run --scenario ext_discovery --gif`
