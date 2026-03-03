# Scenario 11: ext_multi_file — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `ext_multi_file` |
| Result | **PASS (no assertions, partial agent discovery)** |
| Duration | 73.3s (runner) / 52.5s (recording) |
| Cast file | `ext_multi_file_20260303_123350.cast` |
| Frames | 38 |

## What the Scenario Does

1. Opens `schema.py`, opens panel, navigates to line 8 (SchemaError), then line 16 (validate)
2. Opens `loader.py`, navigates through lines 12, 29, 39
3. Opens `merge.py`, navigates to line 8 (deep_merge), then line 19 (merge_dicts)
4. Final stable wait, captures pane (no assertion)

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 4 | 5.5s | `schema.py` loaded |
| 5-12 | 6.7-13.9s | Panel opened, focus right/left |
| 13-14 | 15.0-15.3s | `:8` — on SchemaError. Panel: **"No agent at cursor"** |
| 16-17 | 19.1-19.6s | `:16` — on validate. Panel: **"No agent at cursor"** |
| 18-20 | 33.0-35.2s | Wait, then `:e loader.py` |
| 21-22 | 38.9-39.4s | `:12` — on load_config. Panel: **"No agent at cursor"** |
| 24 | 43.3s | `:29` — on detect_format |
| 26 | 44.2s | `:39` — on load_yaml |
| 28-30 | 45.7-46.3s | `:e merge.py` |
| 32-34 | 50.9-51.4s | `:8` — on deep_merge. Panel: **`? deep_merge` (function, 8-16, Tools: 3)** |
| 36-37 | 52.2-52.5s | `:19` — on merge_dicts. Panel: **`? merge_dicts` (function, 19-26, Tools: 3)** |

## Findings

### Agent Discovery Delayed for First Two Files

- **schema.py**: "No agent at cursor" at both line 8 (SchemaError) and line 16 (validate)
- **loader.py**: "No agent at cursor" at line 12 (load_config)
- **merge.py**: Agents appear correctly — `deep_merge` (function, lines 8-16) and `merge_dicts` (function, lines 19-26)

This pattern suggests the LSP needs more time to discover agents. By the third file, enough time has elapsed (~50s since nv2 started) for agents to be available.

### Panel Shows "No agent at cursor" with Tools (0)

When agents aren't discovered yet, the panel shows Tools (0) instead of Tools (3). Once discovered (merge.py), it correctly shows Tools (3).

### No Assertions

The scenario only captures `_content` at the end with no assertion. It's purely a "visual demo" scenario that passes regardless of whether agents are discovered.

### No Extension-Specific Verification

The scenario's docstring mentions ClassDocGenerator for SchemaError and FunctionTestScaffold for functions, but none of this is verified. The panel doesn't show extension names in the frames we captured.

## Classification

**No-assertion pass** — Navigation works, panel opens, and agent discovery eventually succeeds on the third file. But nothing is asserted, and the first two files don't show agents.

## Recommendations

1. Add wait/retry logic for agent discovery before navigating to function lines
2. Assert that panel shows specific agent names at each navigation point
3. Verify extension type names if they're displayed somewhere in the panel
4. Consider adding `wait_for_text("? SchemaError")` after goto_line(8) to confirm agent readiness
