# PLAN — Custom Node Extensions Demo

**ABSOLUTE RULE: NO SUBAGENTS (Task tool). Do ALL work directly.**

## Table of Contents

1. [Phase 1: Extension Implementation (TDD)](#phase-1) — Write the 3 extension config files with unit tests
2. [Phase 2: Projection Integration Tests](#phase-2) — Verify extensions populate nodes table correctly
3. [Phase 3: Subscription Routing Integration Tests](#phase-3) — Verify events route to correct agents
4. [Phase 4: E2e Cascade Demo Test](#phase-4) — Full chain test with headless runner
5. [Phase 5: Final Verification](#phase-5) — Full test suite passes at baseline

---

## Phase 1: Extension Implementation (TDD) <a id="phase-1"></a>

### Step 1.1: Unit tests for ClassDocGenerator (FAILING first)

**File**: `tests/unit/test_custom_extensions.py`

Write tests that:
- `ClassDocGeneratorExtension.matches("class", "MyClass")` returns True
- `ClassDocGeneratorExtension.matches("function", "my_func")` returns False
- `ClassDocGeneratorExtension.matches("class", "MyClass", file_path="src/foo.py", source_code="class MyClass: ...")` returns True (widened API)
- `get_extension_data()` returns dict with:
  - `extension_name` = "ClassDocGenerator"
  - `custom_system_prompt` is non-empty string containing "documentation"
  - `extra_tools` is a list with one ToolSchema-compatible dict for `create_doc_file`
  - `extra_subscriptions` is a list with SubscriptionPattern-compatible dicts

### Step 1.2: Implement ClassDocGenerator extension

**File**: `remora_demo/project/.remora/models/class_doc_generator.py`

### Step 1.3: Unit tests for FunctionTestScaffold (FAILING first)

Add to `tests/unit/test_custom_extensions.py`:
- `FunctionTestScaffoldExtension.matches("function", "calculate")` returns True
- `FunctionTestScaffoldExtension.matches("function", "test_calculate")` returns False (excludes test_ prefix)
- `FunctionTestScaffoldExtension.matches("class", "MyClass")` returns False
- `FunctionTestScaffoldExtension.matches("method", "process")` returns False (only functions, not methods)
- `get_extension_data()` returns:
  - `extension_name` = "FunctionTestScaffold"
  - `custom_system_prompt` containing "test"
  - `extra_tools` with `create_test_file` tool schema

### Step 1.4: Implement FunctionTestScaffold extension

**File**: `remora_demo/project/.remora/models/function_test_scaffold.py`

### Step 1.5: Unit tests for SwarmMonitor (FAILING first)

Add to `tests/unit/test_custom_extensions.py`:
- `SwarmMonitorExtension.matches("file", "MONITOR.md")` returns True
- `SwarmMonitorExtension.matches("file", "README.md")` returns False
- `SwarmMonitorExtension.matches("function", "MONITOR.md")` returns False (must be file type)
- `get_extension_data()` returns:
  - `extension_name` = "SwarmMonitor"
  - `custom_system_prompt` containing "observe" or "monitor"
  - `extra_subscriptions` subscribing to `ToolCallEvent`, `AgentErrorEvent`, `AgentCompleteEvent`
  - No `extra_tools` (uses rewrite_self only)

### Step 1.6: Implement SwarmMonitor extension

**File**: `remora_demo/project/.remora/models/swarm_monitor.py`

---

## Phase 2: Projection Integration Tests <a id="phase-2"></a>

### Step 2.1: Test projection populates extension fields

Add to `tests/unit/test_custom_extensions.py` (or `tests/unit/test_projections.py`):

Test that when `NodeProjection` is configured with our 3 extensions + existing 2:
- A `NodeDiscoveredEvent` for a class → row has `extension_name="ClassDocGenerator"`, non-empty `custom_system_prompt`, JSON-serialized `extra_tools` and `extra_subscriptions`
- A `NodeDiscoveredEvent` for a non-test function → row has `extension_name="FunctionTestScaffold"`
- A `NodeDiscoveredEvent` for `MONITOR.md` file → row has `extension_name="SwarmMonitor"`
- A `NodeDiscoveredEvent` for `test_foo` function → row has `extension_name="TestAgent"` (existing extension, first-match alphabetical)
- A `NodeDiscoveredEvent` for `__init__.py` file → row has `extension_name="PackageInit"` (existing)
- Hydration via `AgentNode.from_row()` correctly deserializes `extra_tools` to `list[ToolSchema]` and `extra_subscriptions` to `list[SubscriptionPattern]`

---

## Phase 3: Subscription Routing Integration Tests <a id="phase-3"></a>

### Step 3.1: Test subscription patterns from extensions match correct events

Test that the `SubscriptionPattern`s returned by each extension actually match the intended events:
- ClassDocGenerator's subscription matches `ContentChangedEvent` for relevant paths
- SwarmMonitor's subscription matches `ToolCallEvent`, `AgentErrorEvent`, `AgentCompleteEvent`
- SwarmMonitor's subscription does NOT match `ContentChangedEvent` (not subscribed)

### Step 3.2: Test subscription registry routing with extension-sourced patterns

Using `SubscriptionRegistry`:
- Register subscriptions from extension data for multiple agents
- Emit various events and verify `get_matching_agents()` returns the correct set

---

## Phase 4: E2e Cascade Demo Test <a id="phase-4"></a>

### Step 4.1: E2e cascade test

**File**: `tests/integration/test_custom_extensions_cascade.py`

Test the full chain:
1. Set up `EventStore` + `SubscriptionRegistry` + `NodeProjection` with all extensions
2. Emit `NodeDiscoveredEvent` for a class → projection creates node with ClassDocGenerator data
3. Register the extension's `extra_subscriptions` into the `SubscriptionRegistry`
4. Emit a `ContentChangedEvent` for the class's file → verify the ClassDocGenerator agent is in `get_matching_agents()`
5. Emit `NodeDiscoveredEvent` for a non-test function → projection creates node with FunctionTestScaffold data
6. Emit `NodeDiscoveredEvent` for `MONITOR.md` → projection creates node with SwarmMonitor data
7. Register SwarmMonitor's subscriptions → emit `AgentCompleteEvent` → verify MONITOR.md agent is in `get_matching_agents()`
8. Verify the full cascade: multiple agents are correctly triggered by a single event chain

---

## Phase 5: Final Verification <a id="phase-5"></a>

### Step 5.1: Run the full test suite

```bash
python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q --no-cov
```

Expected: 659 + new tests = all passing, 2 xfailed, 0 failures.

---

**REMINDER: NO SUBAGENTS. Do ALL work directly.**
