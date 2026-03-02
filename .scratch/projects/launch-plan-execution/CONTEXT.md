# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 1 COMPLETE — ready to commit and start Batch 2
- **Next action:** Commit Batch 1, then begin Batch 2 (Track B Medium Items), item 2.1

## What Just Happened
- Completed all 25 Batch 1 items (Track A Quick Fixes)
- Fixed remaining items 1.24 (watcher double-parse — confirmed false positive) and 1.25 (code fence language tags)
- Fixed LSP test `test_lsp_handlers_register_and_advertise_capabilities` — `workspace/executeCommand` is a pygls builtin_feature, not a user feature; also removed broken `server_capabilities` monkey-patch test
- Full test suite passes (only failure: `test_real_vllm_grail_tool_execution` — needs running vLLM server, infrastructure only)
- PROGRESS.md updated with all Batch 1 items marked done

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py -q`
- All work is in `src/remora/` — `remora_demo/` is out of scope
- Tests in `tests/unit/test_graph_*.py` and `tests/unit/test_web_layout.py` depend on `remora_demo` — ignore them

## All Batch 1 Changes (uncommitted)

**Source files modified:**
- `src/remora/core/swarm_executor.py` — fixes 1.1 (emit_event), 1.2 (model_name), 1.25 (code fence lang tags + `_lang_tag_for` helper + `_LANG_TAGS` dict)
- `src/remora/core/chat.py` — fix 1.3 (.close() not .cleanup())
- `src/remora/core/projections.py` — fixes 1.4 (`_dataclass_default`), 1.5 (removed conn.commit())
- `src/remora/core/agent_node.py` — fixes 1.4 (asdict), 1.22 (removed hashlib)
- `src/remora/core/event_store.py` — fix 1.5 (single txn commit after projection)
- `src/remora/core/discovery.py` — fixes 1.10 (TreeSitterDiscoverer), 1.11 (NodeType, Enum import)
- `src/remora/core/config.py` — fix 1.16 (consolidated ConfigError import)
- `src/remora/core/events.py` — fix 1.23 (tags → tuple[str, ...])
- `src/remora/cli/main.py` — fixes 1.6 (nvim removal), 1.23 (tags tuple)
- `src/remora/ui/view.py` — fix 1.14 (removed render_tag)
- `src/remora/ui/__init__.py` — fix 1.14 (removed render_tag export)
- `src/remora/core/__init__.py` — fixes 1.10, 1.11 (removed exports)
- `src/remora/__init__.py` — fixes 1.10, 1.11 (removed exports)
- `src/remora/service/handlers.py` — fix 1.23 (tags tuple)

**Test files modified:**
- `tests/integration/test_lsp_integration.py` — fix 1.17 (imports + corrected capability assertions)
- `tests/roundtrip/run_harness.py` — fix 1.11 (NodeType → string list)

**Deleted files:**
- `src/remora/nvim/` (entire package)
- `src/remora/core/vcs.py`
- `plugin/remora_nvim.lua` + `plugin/` directory
- `load.vim`
- `tests/helpers.py`
- `tests/fixtures/mock_llm.py`

## Key Decisions
- `NodeType` enum → plain string list `["file", "class", "function", "method", "section", "table"]`
- Projection `conn.commit()` removed — EventStore owns the single commit
- `_dataclass_default` helper for recursive dataclass→JSON serialization
- `AgentMessageEvent.tags` → immutable `tuple[str, ...]`
- LSP `__init__.py` exports verified correct — no changes needed
- Neovim Lua files (N1-N4) already deleted — N/A
- Watcher double-parse (L4) — false positive, single parse at line 47
- LSP test: `workspace/executeCommand` is a pygls builtin, not user feature; test updated to check `fm.builtin_features` and `fm.commands`

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Commit Batch 1 changes
5. Begin Batch 2 item 2.1 (RemoraDB dual-write elimination)
