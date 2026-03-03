# CONTEXT — Custom Node Extensions Demo

## Current State: PROJECT COMPLETE (with E2E + Bug Fixes)

All phases (1-4) plus E2E scenarios and two bug fixes are fully implemented and tested.

## What Was Done

### Phase 1-4: Extensions + Tests (original scope)

Implemented three custom `AgentExtension` configs that demonstrate Remora's reactive event-driven architecture:

| Extension | File | Matches | Purpose |
|-----------|------|---------|---------|
| **ClassDocGenerator** | `remora_demo/project/.remora/models/class_doc_generator.py` | `node_type == "class"` | Equips class agents with `create_doc_file` tool; subscribes to `ContentChangedEvent`/`NodeDiscoveredEvent` |
| **FunctionTestScaffold** | `remora_demo/project/.remora/models/function_test_scaffold.py` | `node_type == "function"` AND NOT `test_*` prefix | Equips function agents with `create_test_file` tool; subscribes to `NodeDiscoveredEvent`/`ContentChangedEvent` |
| **SwarmMonitor** | `remora_demo/project/.remora/models/swarm_monitor.py` | `node_type == "file"` AND `name == "MONITOR"` | Meta-observer subscribing to `AgentCompleteEvent`/`AgentErrorEvent`/`ToolCallEvent` — no extra tools, uses `rewrite_self` only |

### Phase 5: Bug Fixes

1. **Stem-name bug**: `ASTWatcher._parse_file_only()` uses `Path(uri).stem` for file-level node names, so `MONITOR.md` becomes `name="MONITOR"` (not `"MONITOR.md"`). Fixed extension configs and all test references.

2. **FunctionTool adapter**: `build_chat_tools()` called `Tool.from_function()` which doesn't exist — `Tool` is a Protocol. Created `FunctionTool` class in `src/remora/core/chat.py` that wraps async callables into the `Tool` protocol, auto-generating `ToolSchema` from function signatures. Removed xfail markers from the 2 `TestBuildChatTools` tests.

### Phase 6: E2E Scenarios + GIF Recording

Three new E2E scenarios drive nv2 via tmux and record terminal output:

| Scenario | File | Description |
|----------|------|-------------|
| `ext_discovery` | `e2e/scenarios/ext_discovery.py` | Open schema.py (class+function), browse, open panel |
| `ext_multi_file` | `e2e/scenarios/ext_multi_file.py` | Navigate schema.py -> loader.py -> merge.py |
| `ext_edit_cascade` | `e2e/scenarios/ext_edit_cascade.py` | Edit SchemaError + load_config, watch extensions react |

GIF recording requires `devenv shell` for `agg`:
```bash
devenv shell -- python -m e2e.run --scenario ext_discovery --gif
```

### Tests

| File | Count | Scope |
|------|-------|-------|
| `tests/unit/test_custom_extensions.py` | 42 | Unit: matches/data, projection integration, subscription pattern matching |
| `tests/integration/test_custom_extensions_cascade.py` | 10 | E2e cascade: discovery->extension->subscribe->trigger chain |

**713 passed, 0 xfailed, 0 failures, 2 warnings**

### Key Principle

**No core library files were modified for extensions.** All extensions are pure configuration. The only core file changed was `src/remora/core/chat.py` to fix the `FunctionTool` adapter bug (pre-existing, not related to extensions).

## Test Command

```bash
python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q --no-cov
```
