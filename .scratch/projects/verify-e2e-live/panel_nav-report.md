# Scenario 8: panel_nav — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `panel_nav` |
| Result | **PASS (genuine)** |
| Duration | 43.1s (runner) / 21.4s (recording) |
| Cast file | `panel_nav_20260303_122703.cast` |
| Frames | 23 |

## What the Scenario Does

1. Opens `loader.py`, waits for `def load_config`
2. Opens Remora agent panel (`<leader>ra`)
3. Focuses into panel then back
4. Goes to line 12 — asserts `load_config` in pane
5. Goes to line 29 — asserts `detect_format` in pane
6. Goes to line 39 — asserts `load_yaml` in pane
7. Focuses into panel, toggles tools with `t` twice
8. Closes panel with `q`
9. Waits for stable

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 3 | 2.7s | Editor loaded |
| 5-7 | 3.5-6.7s | Panel opened, focus right/left |
| 8 | 7.8s | Panel shows "No agent at cursor" (cursor at line 1) |
| 12 | 10.7s | After `:12` — panel shows `? loader` (file-level agent) |
| 13 | 11.0s | Panel updates to `? load_config`, Type: function, Lines: 12-26, with chat history |
| 14 | 13.3s | After `:29` — cursor on `detect_format`, panel still shows `load_config` |
| 15 | 13.9s | Panel updates to `? detect_format`, Type: function, Lines: 29-36 |
| 17 | 16.2s | After `:39` — panel still shows `detect_format` |
| 18 | 16.6s | Panel updates to `? load_yaml`, Type: function, Lines: 39-44 |
| 19-20 | 18.7-19.2s | Focus into panel, `t` toggle tools |
| 21 | 20.3s | Second `t` toggle |
| 22 | 21.4s | Panel closed with `q`, single pane restored |

## Findings

### Panel Navigation Works Correctly

This is the best-functioning scenario so far. The panel:
- Opens successfully with `<leader>ra`
- Shows agent info (name, type, status, line range)
- Updates when cursor moves between functions
- Shows correct agent at each position:
  - Line 12: `load_config` (function, lines 12-26)
  - Line 29: `detect_format` (function, lines 29-36)
  - Line 39: `load_yaml` (function, lines 39-44)
- Shows "No agent at cursor" when cursor is at file top (line 1)
- Closes cleanly with `q`

### Chat History Persists

Frame 13 shows chat history from a previous session:
- "what does this function do?" (22:18:16)
- "what do you do?" (12:17:22)

This indicates the demo project's chat state persists between scenario runs. This is expected but worth noting for test isolation.

### Tools Section Toggle

The `t` key toggle fires (visible in frames 19-21) but the tools section stays collapsed (`▶ Tools (3)`) — the toggle may need the focus to be on the panel content area rather than the input area. Hard to tell from frames alone.

### Assertions Are Valid (but weak)

The assertions check `"load_config" in content`, `"detect_format" in content`, `"load_yaml" in content`. These pass because the function names appear in both the code and the panel. However, the panel IS correctly updating — the agent name in the panel sidebar changes at each step. Stronger assertions would check specifically for the panel agent name format (e.g., `? load_config`).

## Classification

**Genuine pass** — Panel opens, updates with cursor movement across three functions, and closes cleanly. All core behaviors work as intended.

## Recommendations

1. Strengthen assertions to check panel-specific content (e.g., `"? load_config"` or `"Type: function"`)
2. Consider clearing chat history between scenario runs for isolation
3. Verify the tools toggle actually expands/collapses (hard to assert from capture_pane alone)
