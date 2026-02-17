# DEV GUIDE STEP 15: Results Aggregation + Formatting

## Goal
Build the result aggregation models and output formatters that present analysis results to the user — table, JSON, and interactive review mode.

## Why This Matters
The runner layer produces raw `AgentResult` and `NodeResult` objects. Users need to see these in a form that lets them quickly understand what happened and decide what to accept. The formatters are the last mile between the agent system and the human reviewing its output.

## Implementation Checklist
- Implement `AnalysisResults` model (top-level container for all `NodeResult` objects).
- Implement `TableFormatter` — renders a node × operation grid using Rich tables.
- Implement `JSONFormatter` — renders the full `AnalysisResults` as indented JSON.
- Implement `InteractiveFormatter` — step-through prompts for accept/reject per operation.
- Implement `ResultPresenter` orchestrator that picks the right formatter based on `--format` flag.
- Add failure summaries: when an operation fails, show the error message and suggest a retry command.

## Suggested File Targets
- `remora/results.py` (models + formatters)
- `remora/models.py` (update `AnalysisResults`)

## AnalysisResults Model

```python
class AnalysisResults(BaseModel):
    nodes: list[NodeResult]
    total_nodes: int
    successful_operations: int
    failed_operations: int
    skipped_operations: int

    @classmethod
    def from_node_results(cls, results: list[NodeResult]) -> "AnalysisResults":
        successful = sum(
            1 for nr in results
            for ar in nr.operations.values()
            if ar.status == "success"
        )
        failed = sum(
            1 for nr in results
            for ar in nr.operations.values()
            if ar.status == "failed"
        )
        skipped = sum(
            1 for nr in results
            for ar in nr.operations.values()
            if ar.status == "skipped"
        )
        return cls(
            nodes=results,
            total_nodes=len(results),
            successful_operations=successful,
            failed_operations=failed,
            skipped_operations=skipped,
        )
```

## Table Formatter Output

```
┌──────────────────────────────┬──────────┬──────────┬─────────────┐
│ Node                         │ lint     │ test     │ docstring   │
├──────────────────────────────┼──────────┼──────────┼─────────────┤
│ src/utils.py::calculate      │ ✓ (3 fx) │ ✓ (5 t)  │ ✓ added     │
│ src/utils.py::format_string  │ ✓ (0 fx) │ ✓ (2 t)  │ ✗ failed    │
│ src/models.py::User          │ ✓ (1 fx) │ ─ skip   │ ✓ updated   │
└──────────────────────────────┴──────────┴──────────┴─────────────┘
Summary: 3 nodes, 7/9 operations succeeded, 1 failed, 1 skipped
```

Status symbols:
- `✓` — success (with brief detail from `summary`)
- `✗` — failed (show error code)
- `─` — skipped

## JSON Formatter Output

```json
{
  "total_nodes": 3,
  "successful_operations": 7,
  "failed_operations": 1,
  "skipped_operations": 1,
  "nodes": [
    {
      "node_id": "abc123",
      "node_name": "calculate",
      "file_path": "src/utils.py",
      "operations": {
        "lint": {
          "status": "success",
          "workspace_id": "lint-abc123",
          "changed_files": ["src/utils.py"],
          "summary": "Fixed 3 issues",
          "details": {"issues_fixed": 3, "issues_remaining": 0},
          "error": null
        }
      },
      "errors": []
    }
  ]
}
```

## Interactive Formatter

The interactive formatter prompts per operation for each node:

```
src/utils.py::calculate

  lint:  Fixed 3 issues (E225, F401, W291) → src/utils.py
  [a]ccept  [r]eject  [s]kip  [d]iff  [?]help  > _
```

Commands:
- `a` — accept (calls `RemoraAnalyzer.accept()`)
- `r` — reject (calls `RemoraAnalyzer.reject()`)
- `s` — skip for now (leave workspace pending)
- `d` — show workspace diff before deciding
- `q` — quit interactive mode

## Implementation Notes
- The `TableFormatter` uses Rich's `Table` class. Use color coding: green for success, red for failed, grey for skipped.
- The `InteractiveFormatter` should show the workspace diff inline when `d` is pressed (call Cairn's diff API).
- Both `TableFormatter` and `JSONFormatter` should work non-interactively (no stdin required) for piping output to files.
- `ResultPresenter` chooses formatter based on `--format` flag values: `table` (default), `json`, `interactive`.

## Testing Overview
- **Unit test:** `AnalysisResults.from_node_results()` correctly counts success/failed/skipped across nodes.
- **Unit test:** `TableFormatter` output contains all node names and operation names.
- **Unit test:** `JSONFormatter` output is valid JSON that validates against the schema.
- **Unit test:** Failed operations appear with error indicators in table output.
- **Unit test:** Skipped operations show the skip symbol.
- **Integration test:** `remora analyze --format json src/fixture.py` produces parseable JSON output.
