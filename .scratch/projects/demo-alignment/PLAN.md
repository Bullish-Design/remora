# Plan

**NO SUBAGENTS. Do all work directly.**

## Goal

For each functional area, produce a guide that accurately describes the actual implementation and concretely documents what must change to make it fully functional and fully aligned with the current architecture.

## Ordered Tasks

### Phase 1 — Analysis (complete)
- [x] Read architecture refactor PROGRESS.md files (both complete, 0 cycles)
- [x] Read CRITICAL_RULES.md
- [x] Read all four functional areas deeply (Lua plugin, web graph, chat service, companion)
- [x] Read agent_runner.py, event_emitter.py, event_store_queries.py, agent_events.py, interaction_events.py
- [x] Identify concrete bugs (panel.lua AgentMessageEvent, state.py schema, etc.)

### Phase 2 — Guide Files (in progress)
- [ ] Rewrite GUIDE_NEOVIM.md (currently wrong — was about mock_llm.py)
- [ ] Verify GUIDE_AGENT_CHAT.md is still accurate (looks correct)
- [ ] Confirm GUIDE_WEB_UI.md is accurate (looks correct)
- [ ] Verify GUIDE_COMPANION.md is still accurate (looks correct)
- [ ] Update README.md with corrected findings
- [ ] Create scaffold files (PROGRESS.md, CONTEXT.md, PLAN.md, DECISIONS.md, ASSUMPTIONS.md, ISSUES.md)

### Phase 3 — Implement Fixes (pending)
- [ ] Fix state.py schema bugs (events: event_id→id, agent_id→from_agent/to_agent; nodes: id→node_id)
- [ ] Fix tests/test_bridge.py schema to match production
- [ ] Fix panel.lua AgentMessageEvent bugs (3 bugs: routing, direction display, dedup)
- [ ] Fix chat_service.py singleton anti-pattern

## Acceptance Criteria

1. All guide files accurately describe the actual implementation (not mock/demo harnesses)
2. All critical bugs documented with concrete fix code
3. `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` still passes
4. `devenv shell -- tach check` still passes
