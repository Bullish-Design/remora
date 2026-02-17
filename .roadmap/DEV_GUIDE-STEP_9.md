# DEV GUIDE STEP 9: Test Subagent Tool Scripts

## Goal
Implement all `.pym` tool scripts, the context provider, and the complete YAML definition file for the test generation subagent.

## Why This Matters
The test subagent is the most multi-turn of the four domains. Generating tests that actually pass requires iterating: analyze the signature, write tests, run them, and fix failures. This step establishes the pattern of using `run_tests` as a feedback loop, which the fine-tuned model will learn from training data generated in Step 12.

## Implementation Checklist
- Write `agents/test/test_subagent.yaml` with model path, initial context, and full tool set.
- Write `agents/test/tools/analyze_signature.pym` — extract function name, parameter names, types, defaults, and return type from the node text.
- Write `agents/test/tools/read_existing_tests.pym` — read the existing test file for this module if it exists; return empty string otherwise.
- Write `agents/test/tools/write_test_file.pym` — write test content to the appropriate test file path in the workspace.
- Write `agents/test/tools/run_tests.pym` — run pytest on the workspace copy; return pass/fail/error per test.
- Write `agents/test/tools/submit.pym` — return standard agent result schema.
- Write `agents/test/context/pytest_config.pym` — read `pytest.ini` or `[tool.pytest.ini_options]` from `pyproject.toml`; return raw config text.

## Suggested File Targets
- `agents/test/test_subagent.yaml`
- `agents/test/tools/analyze_signature.pym`
- `agents/test/tools/read_existing_tests.pym`
- `agents/test/tools/write_test_file.pym`
- `agents/test/tools/run_tests.pym`
- `agents/test/tools/submit.pym`
- `agents/test/context/pytest_config.pym`

## Tool Contracts

### analyze_signature.pym
**Input:** `{}`
**Output:**
```json
{
  "function_name": "calculate_total",
  "parameters": [
    {"name": "price", "type": "float", "default": null},
    {"name": "quantity", "type": "int", "default": 1},
    {"name": "discount", "type": "float", "default": 0.0}
  ],
  "return_type": "float",
  "is_async": false
}
```

### read_existing_tests.pym
**Input:** `{}`
**Output:** `{"content": "import pytest\n...", "path": "tests/test_utils.py"}` or `{"content": "", "path": null}`

### write_test_file.pym
**Input:** `{"content": "<test file text>", "path": "tests/test_utils.py"}`
**Output:** `{"success": true, "path": "tests/test_utils.py"}`

### run_tests.pym
**Input:** `{"path": "tests/test_utils.py"}` (optional, defaults to discovered test file)
**Output:**
```json
{
  "passed": 3,
  "failed": 1,
  "errors": 0,
  "failures": [
    {"test": "test_calculate_total_zero_quantity", "message": "AssertionError: expected 0.0, got None"}
  ]
}
```

### submit.pym
**Input:** `{"summary": str, "tests_generated": int, "tests_passing": int, "changed_files": list[str]}`
**Output:** Standard `AgentResult` dict

### pytest_config.pym (context provider)
**Input:** `{}`
**Output:** Pytest configuration text or empty string

## test_subagent.yaml System Prompt Guidance
The system prompt should emphasize:
- Analyze the function signature before writing any tests
- Check for existing tests first to avoid duplicating coverage
- Write tests that cover: normal cases, edge cases (empty, zero, None), and expected exceptions
- After writing tests, always call `run_tests` to verify they pass
- If tests fail, inspect the failure message and revise — don't just submit failing tests

## Test File Path Convention
The test file path convention: `tests/test_{module_name}.py` where `module_name` is the stem of the source file. This should be derived from `node.file_path` in the context rendering.

## Implementation Notes
- `analyze_signature.pym` can use Python's `ast` module to parse the function node text and extract signature details, rather than relying on Tree-sitter.
- `run_tests.pym` must run pytest against the workspace copy of the source + test files (not the host's files). Use Cairn workspace materialization or write to a temp directory.
- The `run_tests.pym` timeout should be generous (30s default) since generated tests may import the module being tested and trigger slow initialization.

## Testing Overview
- **Unit test:** `analyze_signature.pym` on a typed function extracts correct parameters and return type.
- **Unit test:** `analyze_signature.pym` on a function with no type annotations returns `null` types (not an error).
- **Unit test:** `read_existing_tests.pym` returns empty content when no test file exists.
- **Unit test:** `write_test_file.pym` creates file at correct path in workspace.
- **Unit test:** `run_tests.pym` on a passing test returns `{"passed": N, "failed": 0}`.
- **Unit test:** `run_tests.pym` on a failing test includes failure message in output.
- **Unit test:** `submit.pym` output validates against standard `AgentResult` schema.
