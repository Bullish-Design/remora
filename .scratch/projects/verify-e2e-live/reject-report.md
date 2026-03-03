# Scenario 6: reject — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `reject` |
| Result | **PASS (false positive)** |
| Duration | 29.7s (runner) / 20.1s (recording) |
| Cast file | `reject_20260303_122330.cast` |
| Frames | 19 |

## What the Scenario Does

1. Opens `loader.py` in nv2, waits for `def load_config`
2. Goes to line 29 (`detect_format`)
3. Triggers `<leader>rr` (rewrite)
4. Waits for stable (2.0s, timeout 20)
5. Triggers `<leader>rn` (reject)
6. Waits for stable (2.0s, timeout 10)
7. Asserts `def detect_format` is in pane content

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 0-3 | 0.0-1.6s | nv2 launch command |
| 4 | 2.7s | Editor loaded, `detect_format` visible |
| 5 | 3.2s | Status bar fully rendered |
| 6-7 | 5.6-5.9s | `:29` — goto_line executed |
| 8-9 | 6.1-6.4s | Cursor on line 29, `<leader>rr` triggered |
| 10 | 6.7s | Notification visible, agent info shown briefly |
| 12-13 | 7.2-7.7s | **"LSP not running"** notification |
| 14-17 | 11.9-15.1s | Stable period, `<leader>rn` fires (nothing to reject) |
| 18 | 20.1s | Final stable state |

## Findings

### False Positive — Same "LSP not running" Issue

The `<leader>rr` at ~6.4s triggers the same "LSP not running" error seen in scenarios 3 (rewrite) and 4 (proposal). No proposal is ever generated, so the `<leader>rn` reject fires against an empty state.

The assertion `"def detect_format" in content` passes trivially — the file was never modified. This is not verifying rejection; it's verifying that an error left the file unchanged.

### No Actual Reject Path Tested

The scenario intends to verify:
1. Rewrite produces a proposal
2. Reject (`<leader>rn`) discards the proposal
3. File returns to original state

None of these steps actually execute. The test passes for the wrong reason.

## Classification

**False positive** — Passes because the rewrite never executed (LSP not running), not because rejection works correctly.

## Recommendations

1. Fix the underlying "LSP not running" issue (shared with scenarios 3 and 4)
2. Add a positive assertion that a proposal appeared before attempting reject
3. Verify the file content matches original bytes after rejection (not just that a function name is present)
