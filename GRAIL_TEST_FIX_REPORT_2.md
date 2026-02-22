# Grail Test Fix Report 2

## 1. Overview of the Problem

Phase 1 refactoring involved introducing a `run_json_command` utility and updating the `.pym` test and linting tools to use it, shifting the JSON parsing responsibility out of the `.pym` scripts and into the host.

While the syntax and type-checking errors have now been resolved (e.g. by fixing `missing external` declarations in test tools), several functional test failures remain, primarily within the linting flow. In addition, the acceptance tests are outputting a large number of `Warning: Extra input '...' not declared in script` messages. 

## 2. What Has Been Tried Thus Far

- Implemented `run_json_command` in `src/remora/externals.py` and wrapped it in `tests/utils/grail_runtime.py`.
- Refactored `run_linter.pym` to remove its bespoke JSON parsing and substituted it with `run_json_command`.
- Addressed `missing external` warnings by accurately declaring `@external run_json_command` and `@external run_command` at the top of the test utilities.
- Fixed an `unresolved_reference` by reinstating the `_parse_number` utility helper in `run_tests.pym`.
- Updated the parsing logic in `run_linter.pym`'s output to correctly access `issue_data.get("location", {}).get("row", 0)`, as the exact JSON path had changed. 

## 3. Detailed Analysis of Current Failures

### 3.1. Linting Tests Failing (`assert 0 == 1`)

**Failures:**
- `tests/test_lint_tools.py::test_run_linter_parses_issues`
- `tests/test_lint_tools.py::test_lint_flow_updates_file`
- `tests/test_tool_script_snapshots.py::TestLintToolSnapshots::test_run_linter_issues_found_output`

**Symptom:** The tests expect `payload["total"] == 1` or `payload["fixable_count"] == 1`, but they are getting `0`. This means that `run_linter.pym` is successfully executing, successfully parsing JSON, but returning an empty list of issues (`[]`).

**Hypothesis / Root Causes:**
1. **Input Key Mismatch:** In `run_linter.pym`, the input is defined as `target_file_input: str | None = Input("target_file", default=None)`. However, the test explicitly passes `inputs={"target_file_input": "sample.py"}`. Grail might be dropping the input because the test passes the key `"target_file_input"`, but the script is looking for `"target_file"`. If the target file resolves to nothing or the wrong path, Ruff lints an empty string and returns 0 issues, bypassing any exceptions if it falls back silently.
2. **Ruff Command Line Arguments:** The refactored command runs `ruff check --output-format json --select E,W,F target_file`. Previously, it may have just been using default commands or a different `select` scope. The E, W, and F rules might not be triggering for the exact code generated in the test stub, or the test might be executing in an isolated manner where Ruff isn't seeing the file correctly.

### 3.2. Apply Fix Failing (`assert False is True`)

**Failures:**
- `tests/test_lint_tools.py::test_apply_fix_updates_file`

**Symptom:** The test asserts `success` is `True`, but it is evaluating to `False`. 
**Root Cause:** Inside `apply_fix.pym`, `success = False` occurs exactly when `before == after`. This means that `apply_fix.pym` reads the file, runs `ruff check --fix ...`, and the file contents remain entirely unchanged. This is likely cascading from the exact same naming/resolution bug as `run_linter.pym`—if the target file isn't resolving correctly via input bindings, or if Ruff is exiting early, the file won't be modified.

### 3.3. Extra Input Warnings in Pytest

**Symptom:** Huge blocks of warnings during integration tests:
```
Warning: Extra input 'node_text' not declared in script
Warning: Extra input 'workspace_id' not declared in script
...
```

**Root Cause:** As stated in the `HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md` documentation, `"structured-agents does not define a fixed set of system-injected inputs. Any context passed by the consumer is merged with model arguments"`. The runtime kernel is forcefully injecting a vast amount of context (turn data, node text, recent actions, workspace_id, etc.) into the Grail execution context. Because the `.pym` scripts (like `run_linter.pym`) do not explicitly declare these via `@Input(...)` with `default=None`, Grail's strict typechecker warns the developer that unknown arguments are being piped into the script. 

## 4. Recommended Next Steps

When we pick this back up, I suggest the following approach:

### Step 1: Fix Input Bindings in Scripts
Check the `Input(...)` declaration keys in `run_linter.pym` and `apply_fix.pym`.
- Change `Input("target_file")` back to `Input("target_file_input")` to match what the pytest runner is providing in the payload to properly pass `sample.py` down to the Ruff executor.
- Run `uv run grail check agents/lint/tools/run_linter.pym` (and `apply_fix`) to cleanly regenerate the `inputs.json` schema files.

### Step 2: Silence the Extra Input Warnings
Since `structured-agents` forcefully passes the global agent state to every tool, you can either:
1. Ignore the warnings safely (they do not affect functionality).
2. Suppress them globally in the pytest config.
3. Explicitly declare all of those extra arguments as optional inputs at the top of the `.pym` files. e.g.,
   ```python
   workspace_id: str | None = Input("workspace_id", default=None)
   node_text: str | None = Input("node_text", default=None)
   # ... etc
   ```

### Step 3: Verify Ruff Execution
Trace the actual dictionary outputs of `run_json_command` (you can insert a temporary `print(completed)` in `run_linter.pym` wrapped in `except`) and confirm that `sample.py` is being properly located, and that the Pytest test environment hasn't accidentally altered the `cwd` where Ruff is looking.
