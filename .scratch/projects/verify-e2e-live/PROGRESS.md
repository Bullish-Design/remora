# PROGRESS: Verify E2E Live Scenarios

## Status: COMPLETE

All 12 scenarios run, analyzed, and reported. Project complete.

## Preflight
- [x] vLLM server reachable (`http://remora-server:8000/v1`, model `Qwen/Qwen3-4B-Instruct-2507-FP8`)
- [x] No stale tmux sessions
- [x] Harness infrastructure works

## Scenarios

| # | Scenario | Status | Result | Classification | Key Finding | Report |
|---|----------|--------|--------|---------------|-------------|--------|
| 1 | startup | done | PASS (10.9s) | **Genuine** | Works correctly. `[Remora]` at 2.1s, file loaded, pane stable. | `startup-report.md` |
| 2 | chat | done | PASS (27.5s) | **False positive** | `wait_for_text("load_config")` matches file content, NOT LLM response. | `chat-report.md` |
| 3 | rewrite | done | PASS (19.3s) | **False positive** | `<leader>rr` triggers "LSP not running" error. Rewrite never executes. | `rewrite-report.md` |
| 4 | proposal | done | PASS (27.7s) | **False positive** | Same "LSP not running" on `<leader>rr`. Accept fails silently. File unchanged. | `proposal-report.md` |
| 5 | cascade | done | PASS (27.3s) | **Genuine (weak)** | Edit works. Panel shows agent info. No cascade verification. | `cascade-report.md` |
| 6 | reject | done | PASS (29.7s) | **False positive** | Same "LSP not running". No proposal generated, reject is no-op. | `reject-report.md` |
| 7 | multi_file | done | PASS (42.2s) | **Partial false positive** | First chat corrupts source file; second chat works. No LLM verification. | `multi_file-report.md` |
| 8 | panel_nav | done | PASS (43.1s) | **Genuine** | Best scenario. Panel opens/updates/closes correctly. | `panel_nav-report.md` |
| 9 | golden_path | done | PASS (72.0s) | **False positive (no assertions)** | Focus fails after chat, edits go into chat buffer. Zero assertions. `to_llm_tool` error. | `golden_path-report.md` |
| 10 | ext_discovery | done | PASS (49.6s) | **Genuine (weak)** | File loading and panel work. Assertions check file content, not discovery. | `ext_discovery-report.md` |
| 11 | ext_multi_file | done | PASS (73.3s) | **No assertions** | "No agent at cursor" initially, agents appear later. Zero assertions. | `ext_multi_file-report.md` |
| 12 | ext_edit_cascade | done | PASS (57.6s) | **Genuine (no assertions)** | Both edits succeed. Panel correct. Zero assertions. | `ext_edit_cascade-report.md` |

## Summary Statistics

- **Genuine passes**: 3 (startup, panel_nav, ext_edit_cascade — though ext_edit_cascade has no assertions)
- **Genuine (weak)**: 2 (cascade, ext_discovery — pass but don't verify what they claim)
- **False positives**: 4 (chat, rewrite, proposal, reject — pass despite failures)
- **Partial false positive**: 1 (multi_file — half works, half corrupted)
- **No assertions at all**: 2 (golden_path, ext_multi_file — literally cannot fail)

## Cross-Scenario Issues

1. **"LSP not running" on `<leader>rr`** — scenarios 3, 4, 6
2. **Focus management after chat** — scenario 9
3. **Chat text typed into source buffer** — scenario 7
4. **Chat state persists between runs** — scenarios 8, 9, 12
5. **`to_llm_tool` backend error** — scenario 9
6. **No LLM response verification** — all chat scenarios
7. **Agent discovery timing** — scenario 11
8. **Zero assertions** — scenarios 9, 11, 12

## keys.py Improvements Identified
- Need `wait_for_lsp_ready()` helper
- Need better focus management after chat open
- Need chat state clearing for test isolation
