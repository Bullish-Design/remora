# Scenario 9: golden_path — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `golden_path` |
| Result | **PASS (multiple issues, no assertions)** |
| Duration | 72.0s (runner) / 44.2s (recording) |
| Cast file | `golden_path_20260303_122856.cast` |
| Frames | 58 |

## What the Scenario Does

1. Open `loader.py`, scroll down 15 lines, return to top
2. Open agent panel (`<leader>ra`), focus right/left
3. Go to line 13, open chat (`<leader>rc`), type "what do you do?"
4. Focus back to code, go to line 12
5. Find `)`, enter insert mode, type `, timeout: int = 30`
6. Save to trigger cascade
7. Wait 8s for cascade
8. Open `test_loader.py`, go to line 13
9. Accept proposal (`<leader>ry`)
10. Wait for stable, capture pane (no assertion)

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 4-5 | 2.7-3.2s | Editor loaded with panel |
| 6-14 | 5.6-7.7s | Scroll down, return to top |
| 20-28 | 9.3-14.8s | Panel opened, focus right/left |
| 30-31 | 15.9-16.2s | Goto line 13 |
| 32-35 | 16.4-17.5s | `<leader>rc` — chat menu opens, chat input appears |
| 36-38 | 17.8-22.5s | INSERT mode in chat input ("what do you do?") |
| 39-42 | 23.1-23.9s | Focus back to code, goto line 12, find `)`, insert mode |
| 43 | 24.1s | `, timeout: int = 30` typed — **but into chat input, not code** |
| 44 | 24.7s | Escape from insert |
| 45 | 24.9s | `:w` save attempt — **E382: Cannot write, 'buftype' option is set** |
| 46 | 34.9s | After 8s cascade wait (nothing happened) |
| 47-49 | 35.2-35.7s | `:e test_loader.py` |
| 53-54 | 38.4-38.6s | Goto line 13 on test file, `<leader>ry` accept |
| 57 | 44.2s | Final state — test file unchanged |

## Findings

### Critical Bug: Edit Goes to Chat Input, Not Code Buffer

The `nv.focus_window("h")` at Beat 5 was supposed to return focus to the code pane, but focus remained on `remora://input` (the chat input buffer). So:

1. `nv.goto_line(12)` → sends `:12` to the chat input area (frame 43 shows `h:12` as a chat message)
2. `nv.find_char(")")` → enters `f)` in the chat input
3. `nv.enter_insert()` → enters insert mode in the chat input
4. `nv.type_in_insert(", timeout: int = 30")` → types into chat input, visible as `f)i, timeout: int = 30`
5. `nv.save()` → `:w` fails with `E382: Cannot write, 'buftype' option is set` because `remora://input` is a special buffer

### Chat Messages Trigger API Errors

Frame 43 shows chat errors: `Error: 'dict' object has no attribute 'to_llm_tool'`. This is a Remora backend bug — the tool configuration is returned as a dict instead of an object with a `to_llm_tool` method.

### Previous Chat Messages Leak

The chat panel shows messages from previous scenario runs ("what does this function do?" at 22:18:16, "what do you do?" at 12:17:22), confirming chat state persists across runs.

### Source File Never Modified

The `timeout: int = 30` parameter was never added to `load_config` in the actual file. The code buffer is untouched.

### No Cascade Occurred

Since the file was never modified, no cascade was triggered. The 8-second wait (frames 46) passes silently.

### Accept on Unmodified Test File is No-Op

`<leader>ry` fires on `test_loader.py` at line 13, but there's no proposal to accept. The test file is unchanged.

### No Assertions

The scenario captures `_content = driver.capture_pane()` but never asserts anything — the variable is deliberately unused (prefixed with `_`). This means the scenario cannot fail regardless of what happens.

## Classification

**False positive (no assertions)** — The scenario has zero assertions. Every step after Beat 3 (chat) fails silently: edit goes to wrong buffer, save fails, no cascade, no proposal to accept. But the test "passes" because there's nothing to fail.

## Recommendations

1. **Fix focus management**: After chat, `focus_window("h")` doesn't return to the code pane. May need `wincmd h` or explicit window targeting.
2. **Add assertions**: At minimum, assert that:
   - `timeout` appears in the source code after the edit
   - The test file was modified after accept
3. **Fix the `to_llm_tool` error**: Backend tool serialization issue.
4. **Clear chat state between scenario runs**: For test isolation.
5. **Consider restructuring**: The golden path depends on all prior steps succeeding — any failure cascades (ironically) into all subsequent steps failing silently.
