# DEV GUIDE STEP 11: Sample Data Subagent Tool Scripts

## Goal
Implement all `.pym` tool scripts, the context provider, and the complete YAML definition file for the sample data subagent.

## Why This Matters
The sample data subagent is the simplest of the four domains and makes a good final tool script exercise before moving to training. Its tool set is small (three tools), and the task is clearly scoped: analyze a function's signature and produce a fixture file with realistic example inputs. Completing this step means all four subagent tool catalogs are ready to be trained on.

## Implementation Checklist
- Write `agents/sample_data/sample_data_subagent.yaml` with model path, initial context, and tool set.
- Write `agents/sample_data/tools/analyze_signature.pym` — extract function parameter names, types, and defaults (reuse the implementation pattern from the test subagent).
- Write `agents/sample_data/tools/write_fixture_file.pym` — write a JSON or YAML fixture file to the workspace at the appropriate fixtures path.
- Write `agents/sample_data/tools/submit.pym` — return standard agent result schema.
- Write `agents/sample_data/context/existing_fixtures.pym` — list any existing fixture files in the `fixtures/` directory of the workspace; return their names and paths.

## Suggested File Targets
- `agents/sample_data/sample_data_subagent.yaml`
- `agents/sample_data/tools/analyze_signature.pym`
- `agents/sample_data/tools/write_fixture_file.pym`
- `agents/sample_data/tools/submit.pym`
- `agents/sample_data/context/existing_fixtures.pym`

## Tool Contracts

### analyze_signature.pym
**Input:** `{}`
**Output:**
```json
{
  "function_name": "calculate_total",
  "parameters": [
    {"name": "price", "type": "float", "default": null},
    {"name": "quantity", "type": "int", "default": 1}
  ]
}
```
(Identical output format to the test subagent's version — they can share implementation.)

### write_fixture_file.pym
**Input:**
```json
{
  "fixtures": [
    {"price": 9.99, "quantity": 2},
    {"price": 0.0, "quantity": 1},
    {"price": 100.0, "quantity": 10}
  ],
  "format": "json"
}
```
**Output:** `{"success": true, "path": "fixtures/calculate_total_fixtures.json"}`

### submit.pym
**Input:** `{"summary": str, "fixtures_generated": int, "changed_files": list[str]}`
**Output:** Standard `AgentResult` dict

### existing_fixtures.pym (context provider)
**Input:** `{}`
**Output:**
```json
[
  {"name": "calculate_total_fixtures.json", "path": "fixtures/calculate_total_fixtures.json"}
]
```
Or empty list `[]` if no fixtures exist.

## sample_data_subagent.yaml System Prompt Guidance
The system prompt should emphasize:
- Check for existing fixture files first — if fixtures already exist for this function, call submit_result with a note that fixtures were skipped
- Generate realistic, varied example inputs: a normal case, an edge case (zero/empty/None where types allow), and a large/extreme case
- Match input types exactly to the parameter type annotations
- Use JSON format unless the project already uses YAML fixtures

## Fixture File Path Convention
`fixtures/{function_name}_fixtures.json` — derived from `node.name` in the context template.

## Implementation Notes
- The `analyze_signature.pym` here can be a symlink or copy of the one in `agents/test/tools/`. If the codebase is structured as a monorepo or the tool is identical, sharing the implementation via a `shared/` directory is acceptable. Document the choice.
- `write_fixture_file.pym` should validate that `fixtures` is a non-empty list before writing.
- The fixture format should default to JSON. YAML support is optional for MVP.

## Testing Overview
- **Unit test:** `analyze_signature.pym` on a simple function returns correct parameter data.
- **Unit test:** `write_fixture_file.pym` with valid fixture data writes valid JSON to workspace.
- **Unit test:** `write_fixture_file.pym` with empty `fixtures` list returns error without writing.
- **Unit test:** `existing_fixtures.pym` returns empty list when `fixtures/` directory doesn't exist.
- **Unit test:** `existing_fixtures.pym` returns correct listing when fixture files are present.
- **Unit test:** `submit.pym` output validates against standard `AgentResult` schema.
