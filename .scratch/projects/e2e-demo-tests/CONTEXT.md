# E2E Demo Tests — Context

## Status: COMPLETE

All tasks done. All 9 e2e scenarios pass (9/9, ~280s total) against real vLLM.

## Summary of All Changes Made

### Bug Fixes (production code)

1. **Fixed "No agent found at cursor"** — `src/remora/lsp/__init__.py:main()`
   now creates EventStore + SubscriptionRegistry before calling `_main()`,
   matching what `cli/main.py` does.

2. **Fixed mock LLM not activating** (now reverted — see #6 below)

3. **Added defensive DB migration** — Both `RemoraDB._init_schema()` (db.py)
   and `EventStore._migrate_routing_fields()` (event_store.py) now check for
   and add the `file_path` column to the `proposals` table if missing.

4. **Added env var expansion in config** — `src/remora/core/config.py` expands
   `${VAR:-default}` patterns in YAML config values via `_expand_env_vars()`.

5. **Fixed chat history lost on navigate away/back** — Two issues in
   `src/remora/core/event_store.py`:
   - `append()` stored `type(event).__name__` (e.g. `"LspHumanChatEvent"`) as
     `event_type` column instead of the model's `event_type` field
     (`"HumanChatEvent"`). Panel.lua matches on the canonical string.
   - `_row_to_dict()` returned the raw `model_dump()` blob as `payload`,
     which meant `ev.payload.message` in Lua resolved to `nil` because
     `message` was at the top level of the blob, not nested under `payload`.
     Fixed to reconstruct a proper `payload` sub-dict from model-specific
     fields.

6. **Panel input box enlarged** — `panel.lua` now sets input window height to
   `max(5, floor(vim.o.lines * 0.20))` instead of hardcoded 3 lines.

### Switch to Real vLLM

5. **Removed mock LLM wiring** — `src/remora/lsp/__main__.py` always uses
   real `LLMClient` now. MockLLMClient still exists as dead code.

6. **Config defaults point to vLLM** — `remora_demo/project/remora.yaml` defaults:
   - `model_base_url: ${REMORA_LLM_URL:-http://remora-server:8000/v1}`
   - `model_default: ${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}`

### E2E Framework

7. **Created `e2e/keys.py`** — `NvimKeys` helper class centralizing all
   Neovim keystroke patterns.

8. **9 scenarios total** — all passing against real vLLM with recording + GIF:
   - `startup` (11.8s) — LSP connects, agents discovered
   - `chat` (29.1s) — chat with load_config agent, verify response
   - `rewrite` (18.8s) — trigger rewrite, wait for diagnostic
   - `proposal` (26.5s) — trigger rewrite + accept
   - `cascade` (27.4s) — edit triggers cascade to test agent
   - `golden_path` (69.2s) — full flow: startup→chat→edit→cascade→accept
   - `reject` (27.1s) — trigger rewrite + reject, verify file unchanged
   - `multi_file` (38.4s) — navigate loader.py→merge.py, chat on both
   - `panel_nav` (32.8s) — open panel, move between functions, toggle tools, close

### Files Modified (latest session)

| File | Changes |
|------|---------|
| `e2e/scenarios/reject.py` | NEW — reject proposal scenario |
| `e2e/scenarios/multi_file.py` | NEW — multi-file navigation + chat scenario |
| `e2e/scenarios/panel_nav.py` | NEW — panel navigation scenario |
| `e2e/scenarios/__init__.py` | Added 3 new scenarios to registry |
| `e2e/harness.py` | Added merge.py + test_merge.py to DemoProjectGuard |

### GIF Output

All GIFs in `e2e/output/`:
- `startup_20260302_220147.gif`
- `chat_20260302_220159.gif`
- `rewrite_20260302_220228.gif`
- `proposal_20260302_220247.gif`
- `cascade_20260302_220313.gif`
- `golden_path_20260302_220340.gif`
- `reject_20260302_220450.gif`
- `multi_file_20260302_220517.gif`
- `panel_nav_20260302_220555.gif`
