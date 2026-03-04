# Scenario 12: ext_edit_cascade — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `ext_edit_cascade` |
| Result | **PASS (genuine, no assertions)** |
| Duration | 57.6s (runner) / 39.0s (recording) |
| Cast file | `ext_edit_cascade_20260303_123614.cast` |
| Frames | 35 |

## What the Scenario Does

1. Opens `schema.py`, opens panel, waits for stable
2. Goes to line 12, opens new line, types `self.severity = "error"`, saves
3. Waits for LSP re-parse
4. Opens `loader.py`, waits for `def load_config`
5. Goes to line 12, finds `)`, inserts `, timeout: int = 30`, saves
6. Waits for extension reaction
7. Focuses into panel and back, final stable wait

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 4-5 | 3.6-4.4s | `schema.py` loaded with panel |
| 8-12 | 7.6-11.2s | Panel opened, focus right/left, stable wait |
| 13-15 | 13.9-14.4s | `:12` goto line 12 |
| 16 | 14.7s | INSERT mode — `o` opens new line |
| 17 | 15.0s | `self.severity = "error"` typed, back to Normal. Panel shows `? __init__` (method, lines 11-13) |
| 18-20 | 15.2-15.8s | `:w` save — **success**: `25L, 774B written`. Formatter notification (non-blocking) |
| 21 | 20.5s | Stable wait period |
| 22-24 | 24.0-24.6s | `:e loader.py` |
| 25-28 | 29.3-30.1s | Stable, `:12` goto line, `f)` find paren |
| 29 | 30.4s | INSERT mode — typing `, timeout: int = 30` |
| 30 | 30.7s | Edit complete. Line 12: `def load_config(path: str | Path, timeout: int = 30) -> dict[str, Any]:` |
| 31-32 | 31.0-31.2s | `:w` save — **success**: `44L, 1137B written` |
| 33-34 | 37.4-39.0s | Final state with panel showing `? load_config` |

## Findings

### Both Edits Execute Correctly

1. **schema.py edit**: `self.severity = "error"` added at line 13 inside `__init__`. The panel immediately shows `? __init__` (Type: method, Lines: 11-13, Tools: 3). Save succeeds.

2. **loader.py edit**: `, timeout: int = 30` inserted into `load_config` signature. The breadcrumb updates to `Fn load_config > Var path > Var timeout`. Panel shows `? load_config` (Type: function, Lines: 12-26, Tools: 3). Save succeeds.

### Panel Agent Discovery Works

Unlike scenarios 3/4/6 (where LSP was "not running"), this scenario successfully gets agent panel content:
- Frame 17: `? __init__` (method agent) on `schema.py`
- Frame 30: `? load_config` (function agent) on `loader.py`

This is consistent with the cascade scenario (#5) which also successfully edits and shows agents. The key difference from failing scenarios: this one opens the panel first (`<leader>ra`), then edits — it doesn't use `<leader>rr` (rewrite) which has the LSP readiness check.

### Chat History Leaks from Previous Runs

Frame 30 shows chat messages from prior scenario runs on `load_config` agent:
- "what does this function do?" (22:18:16)
- "what do you do?" (12:17:22, 12:29:15)
- "h:12" (12:29:19) — this is from golden_path where goto_line leaked into chat

### Formatter Warning

Frame 20 shows "Formatter failed. See :ConformInfo for details" — the auto-formatter can't format the file (likely because ruff or black isn't configured in the demo project). This is non-blocking but could affect file content in CI.

### No Assertions

Like golden_path and ext_multi_file, this scenario only captures pane content without asserting anything. Both edits succeed and saves work, but nothing verifies:
- The edited content is correct
- Extensions reacted to the changes
- Agent state changed after edits

### Demo Project Files Modified

This scenario **actually modifies** `schema.py` and `loader.py` in the demo project. The DemoProjectGuard in the harness should restore these, but this is worth verifying.

## Classification

**Genuine pass (no assertions)** — Both edits succeed, saves work, panel shows correct agents. The actual functionality works well. The only weakness is the lack of assertions to formalize what "working" means.

## Recommendations

1. Add assertions verifying the edit content (e.g., `"timeout: int = 30" in content`)
2. Assert panel shows the correct agent after each edit
3. Verify DemoProjectGuard properly restores modified files
4. Consider checking if extension reaction is visible (status change, notification)
