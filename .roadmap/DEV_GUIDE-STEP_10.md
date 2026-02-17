# DEV GUIDE STEP 10: Docstring Subagent Tool Scripts

## Goal
Implement all `.pym` tool scripts, the context provider, and the complete YAML definition file for the docstring subagent.

## Why This Matters
The docstring subagent demonstrates that FunctionGemma subagents can make precise, surgical edits to source files. Writing a docstring correctly — inserting it at the right location, handling existing docstrings, matching the project style — requires the model to first inspect, then decide, then write. This multi-step nature is exactly what the tool calling loop was designed for.

## Implementation Checklist
- Write `agents/docstring/docstring_subagent.yaml` with model path, initial context, and tool set.
- Write `agents/docstring/tools/read_current_docstring.pym` — parse the node text and extract the existing docstring if present; return null if absent.
- Write `agents/docstring/tools/read_type_hints.pym` — extract parameter type annotations and return type annotation from the node.
- Write `agents/docstring/tools/write_docstring.pym` — inject a new docstring into the source file at the correct indentation and position.
- Write `agents/docstring/tools/submit.pym` — return standard agent result schema.
- Write `agents/docstring/context/docstring_style.pym` — read configured docstring style (google/numpy/sphinx) from project config; return style name as string.

## Suggested File Targets
- `agents/docstring/docstring_subagent.yaml`
- `agents/docstring/tools/read_current_docstring.pym`
- `agents/docstring/tools/read_type_hints.pym`
- `agents/docstring/tools/write_docstring.pym`
- `agents/docstring/tools/submit.pym`
- `agents/docstring/context/docstring_style.pym`

## Tool Contracts

### read_current_docstring.pym
**Input:** `{}`
**Output:**
```json
{"docstring": "Existing docstring text or null", "has_docstring": true}
```
Or:
```json
{"docstring": null, "has_docstring": false}
```

### read_type_hints.pym
**Input:** `{}`
**Output:**
```json
{
  "parameters": [
    {"name": "price", "annotation": "float"},
    {"name": "quantity", "annotation": "int"}
  ],
  "return_annotation": "float",
  "has_annotations": true
}
```

### write_docstring.pym
**Input:** `{"docstring": "<docstring text without triple quotes>", "style": "google"}`
**Output:**
```json
{"success": true, "replaced_existing": false}
```
Or on error:
```json
{"success": false, "error": "Could not find insertion point"}
```

### submit.pym
**Input:** `{"summary": str, "action": "added"|"updated"|"skipped", "changed_files": list[str]}`
**Output:** Standard `AgentResult` dict

### docstring_style.pym (context provider)
**Input:** `{}`
**Output:** `"google"` | `"numpy"` | `"sphinx"` (string, not JSON)

## docstring_subagent.yaml System Prompt Guidance
The system prompt should emphasize:
- Always read the existing docstring first — if it is adequate, call submit_result with `action=skipped`
- Check type hints to populate Args and Returns sections accurately
- Match the style returned by the context provider exactly
- For Google style: use `Args:`, `Returns:`, `Raises:` sections
- For NumPy style: use `Parameters` and `Returns` sections with dashes
- Keep descriptions concise — one sentence per parameter where possible

## write_docstring.pym Implementation Notes

The `write_docstring.pym` script must:
1. Parse the function definition line to find the first line after the colon (and any continuation lines)
2. Determine the correct indentation level (function body indentation)
3. Insert the docstring as a triple-quoted string at the correct position
4. Handle the case where an existing docstring is present (replace vs. insert)

Use Python's `ast` module or simple string parsing. The function source is available in the workspace file.

## Implementation Notes
- `read_current_docstring.pym` can use `ast.get_docstring()` on the parsed function node.
- `write_docstring.pym` must handle both `def func():` (single line) and `def func(\n    arg\n):` (multi-line signature) when finding the insertion point.
- The docstring text passed to `write_docstring.pym` should not include the surrounding triple quotes — the tool adds them. This makes it easier for the model to compose the content.

## Testing Overview
- **Unit test:** `read_current_docstring.pym` on a function with a docstring returns the text.
- **Unit test:** `read_current_docstring.pym` on a function without a docstring returns `null`.
- **Unit test:** `read_type_hints.pym` on a fully typed function returns correct annotations.
- **Unit test:** `read_type_hints.pym` on an untyped function returns empty parameters and `null` return.
- **Unit test:** `write_docstring.pym` inserts correctly after single-line function def.
- **Unit test:** `write_docstring.pym` replaces existing docstring without duplicating it.
- **Unit test:** `docstring_style.pym` returns `"google"` when no project config is present.
