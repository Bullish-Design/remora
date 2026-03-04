# docs/ — Shadow Tree Notes

## Status: KEEP (mostly) + REMOVE outdated docs

### KEEP (current/relevant):
- `EventBased_Concept.md` — **Authoritative** architecture doc. KEEP.
- `ARCHITECTURE.md` — May need updating to EventBased. MODIFY.
- `CONCEPT.md` — Used as pyproject.toml readme. MODIFY.
- `CONFIGURATION.md` — Config reference. KEEP, update.
- `INSTALLATION.md` — Install guide. KEEP, update.
- `SPEC.md` — Spec doc. KEEP.
- `API_REFERENCE.md` — API ref. MODIFY.
- `REMORA_UI_API.md` — UI API. KEEP.
- `TESTING_GUIDELINES.md` — Testing guidelines. KEEP.
- `TROUBLESHOOTING.md` — Troubleshooting. KEEP.
- `Dockerfile.ollama.quickstart` — Docker quickstart. KEEP.

### MODIFY (outdated but salvageable):
- `HOW_TO_CREATE_AN_AGENT.md` — Needs rewrite for EventBased extensions.
- `HOW_TO_USE_GRAIL.md` — Grail-specific. KEEP for now.
- `HOW_TO_USE_STRUCTURED_AGENTS.md` — Still relevant (structured-agents is a dependency).
- `STRUCTURED_AGENTS-HOW_TO_USE_QWEN_MODEL.md` — Model-specific guide. KEEP.

### REMOVE (outdated):
- `reports/cairn_test_coverage.md` — Old report.

### docs/plans/ — KEEP (historical + active):
- `2026-03-02-agentnode-design.md` — Phase 1 design. KEEP (reference).
- `2026-03-02-agentnode-implementation.md` — Phase 1 plan. KEEP (reference).
- `EVENT_ARCHITECTURE_ALIGNMENT.md` — Alignment doc. KEEP.
- `2026-03-01-*` — Various design docs. KEEP as historical reference.
- `2026-02-26-*`, `2026-02-27-*` — Older plans. Could MOVE to archive.

### docs/training_examples/ — MOVE or REMOVE
- Training data for fine-tuning. Duplicated in scripts/training_examples/.
  Either remove from docs/ or from scripts/. Keep one copy.
