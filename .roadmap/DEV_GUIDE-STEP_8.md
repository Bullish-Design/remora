# DEV GUIDE STEP 8: Lint Subagent Tool Scripts

## Goal
Implement all `.pym` tool scripts, the context provider, and the complete YAML definition file for the lint subagent.

## Why This Matters
The lint subagent is the first real domain agent and serves as the reference implementation for the other three. The patterns established here — tool contracts, error returns, workspace file handling — should be replicated consistently in the test, docstring, and sample_data subagents.

## Implementation Checklist
- Write `agents/lint/lint_subagent.yaml` with correct model path, initial context, and tool definitions.
- Write `agents/lint/tools/run_linter.pym` — runs ruff on the target file in the workspace; returns structured issue list.
- Write `agents/lint/tools/apply_fix.pym` — applies a single auto-fixable lint issue by code and line number.
- Write `agents/lint/tools/read_file.pym` — reads the current state of the target file from the workspace.
- Write `agents/lint/tools/submit.pym` — constructs and returns the standard agent result schema.
- Write `agents/lint/context/ruff_config.pym` — reads `ruff.toml` or `[tool.ruff]` from `pyproject.toml`; returns raw config text.

## Suggested File Targets
- `agents/lint/lint_subagent.yaml`
- `agents/lint/tools/run_linter.pym`
- `agents/lint/tools/apply_fix.pym`
- `agents/lint/tools/read_file.pym`
- `agents/lint/tools/submit.pym`
- `agents/lint/context/ruff_config.pym`

## Tool Contracts

### run_linter.pym
**Input:** `{"check_only": bool}` (optional)
**Output:**
```json
{
  "issues": [
    {"code": "E225", "line": 5, "col": 10, "message": "missing whitespace around operator", "fixable": true}
  ],
  "total": 3,
  "fixable_count": 2
}
```

### apply_fix.pym
**Input:** `{"issue_code": "E225", "line_number": 5}`
**Output:**
```json
{"success": true, "message": "Applied fix for E225 at line 5"}
```
Or on error:
```json
{"success": false, "message": "No fixable issue at that location"}
```

### read_file.pym
**Input:** `{}`
**Output:** `{"content": "<full file text>", "lines": 42}`

### submit.pym
**Input:** `{"summary": str, "issues_fixed": int, "issues_remaining": int, "changed_files": list[str]}`
**Output:** Standard `AgentResult` dict (status, workspace_id, changed_files, summary, details, error)

### ruff_config.pym (context provider)
**Input:** `{}`
**Output:** `"[tool.ruff]\nline-length = 88\n..."` or empty string if no config found

## lint_subagent.yaml System Prompt Guidance
The system prompt should emphasize:
- Only apply fixes that are guaranteed to preserve semantics
- Be conservative — when in doubt, report but don't fix
- Always call `run_linter` with `check_only=true` first to understand the full picture before applying any fix
- Call `submit_result` once all fixable issues have been addressed

## Implementation Notes
- `.pym` scripts use the Cairn workspace API. The target file path is determined from the `node_id` injected by the runner (or can be read from a well-known location in the workspace). Establish a convention: each subagent writes and reads from the file at its original path within the workspace.
- `run_linter.pym` should invoke ruff via `subprocess.run(["ruff", "check", "--output-format=json", file_path])` and parse the JSON output.
- `apply_fix.pym` should invoke `ruff check --fix --select <code>` on the workspace file.
- All `.pym` tool scripts must return JSON-serializable dicts — no exceptions should escape (catch all and return `{"error": str(e)}`).

## Testing Overview
- **Unit test:** `run_linter.pym` on a file with known E225 issue returns issue in `issues` list with `fixable=true`.
- **Unit test:** `apply_fix.pym` on a file with E225 issue returns `success=true` and file is updated.
- **Unit test:** `read_file.pym` returns correct content and line count.
- **Unit test:** `ruff_config.pym` returns empty string when no ruff config exists in workspace.
- **Unit test:** `submit.pym` output validates against standard `AgentResult` schema.
- **Integration test:** Run `run_linter → apply_fix → submit` sequence on a fixture file; verify workspace diff shows correct changes.
