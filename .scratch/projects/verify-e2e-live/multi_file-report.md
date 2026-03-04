# Scenario 7: multi_file — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `multi_file` |
| Result | **PASS (partial false positive)** |
| Duration | 42.2s (runner) / 22.5s (recording) |
| Cast file | `multi_file_20260303_122458.cast` |
| Frames | 31 |

## What the Scenario Does

1. Opens `loader.py`, goes to line 12 (`load_config`)
2. Triggers `<leader>rc` (chat), types "what does this function do?", sends
3. Asserts `load_config` visible (via `wait_for_text`)
4. Opens `merge.py` via `:e`, waits for `def deep_merge`
5. Goes to line 8, triggers `<leader>rc`, types "explain this function", sends
6. Waits for stable, asserts `deep_merge` or `merge` in pane

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 4-5 | 2.7-3.2s | Editor loaded, `loader.py` visible |
| 6-7 | 5.6-5.9s | `:12` goto_line |
| 9 | 6.4s | Leader menu visible (Space submenu) |
| 10 | 6.7s | Remora submenu visible (`<Space>r`) |
| 11 | 7.0s | **"LSP not running"** notification |
| 14-15 | 9.1-9.3s | **INSERT mode — chat text typed INTO source file** |
| 16-17 | 9.9-10.4s | Escape + Enter leave the corruption in file |
| 18 | 12.0s | Corrupted file visible: `def t does this function do?` on line 12 |
| 19-20 | 15.4-15.7s | `:e merge.py` file switch |
| 21-24 | 17.5-18.3s | `merge.py` loaded, goto line 8 |
| 25 | 18.6s | Remora submenu for `<leader>rc` — **this time it works** |
| 26 | 19.1s | "Message to agent:" prompt appears correctly |
| 27-29 | 20.6-22.2s | "explain this function" typed in chat input |
| 30 | 22.5s | Recording ends, chat submitted but no LLM response visible |

## Findings

### Critical Bug: First Chat Corrupts Source File

When `<leader>rc` fires on `loader.py` at ~6.4s, the LSP is not running. The command fails silently but leaves the editor in a state where the subsequent `nv.keys("what does this function do?")` is typed into the source buffer in INSERT mode instead of a chat panel.

Frame 14 shows the corrupted source:
```
def t does this function do?
    load_config(path: str | Path) -> dict[str, Any]:
```

The `def ` prefix from line 12 got partially overwritten. The file is marked as modified (`[+]`) and diagnostics show errors (`E19`).

### Second Chat Works Correctly on merge.py

After switching to `merge.py`, the `<leader>rc` successfully opens the "Message to agent:" prompt. The typing goes into the correct chat input, not the file. This suggests the LSP becomes available for the second file (or the second file triggers a fresh LSP initialization).

### No LLM Response Verification

Neither chat interaction verifies an actual LLM response:
- First chat: `wait_for_text("load_config")` matches the function name already in the file
- Second chat: `wait_for_stable` + `"deep_merge" in content` matches file content

### Assertion Passes Trivially

The assertion `"deep_merge" in content or "merge" in content` is guaranteed to pass as long as `merge.py` is visible in the editor.

## Classification

**Partial false positive** — Second file navigation and chat initiation works correctly, but first chat corrupts the source file and neither chat verifies an LLM response.

## Recommendations

1. Fix the LSP timing issue that causes "LSP not running" on first file
2. Add an assertion that the chat panel / "Message to agent:" prompt appears before typing
3. Verify actual LLM responses (look for content NOT already in the file)
4. Check file integrity — the `loader.py` corruption should be caught as a failure
5. Consider adding `wait_for_lsp_ready()` or similar before chat/rewrite commands
