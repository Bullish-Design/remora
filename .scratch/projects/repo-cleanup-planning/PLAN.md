# Repo Cleanup — Plan

**Full analysis:** `REPO_CLEANUP_ANALYSIS.md` (committed as `45e5df7`)

---

## Phase 1: Immediate Cleanup (Zero-Risk Removals)

### 1.1 Delete temp files at root
```
rm tmp_test_add.pym tmp_test_input.pym tmp_test_input2.pym tmp_test_name.pym
rm demo-trigger.py load.vim .ast_summary_events.jsonl
```

### 1.2 Delete `tmp_test_runner/`
```
rm -rf tmp_test_runner/
```

### 1.3 Delete `_review_notes/`
```
rm -rf _review_notes/
```

### 1.4 Delete `remora_demo/.v1/`
```
rm -rf remora_demo/.v1/
```

### 1.5 Delete old root-level docs
```
rm NEOVIM_DEMO_V21_FINAL_CONCEPT.md
rm NEOVIM_DEMO_V24_CODE_REVIEW.md
rm CODE_REVIEW.md
```

### 1.6 Update `.gitignore`
Add patterns:
```gitignore
# AI/dev context
.context/
.claude/
.scratch/

# Runtime artifacts
.grail/
.benchmarks/
.ast_summary_events.jsonl
tmp_test_runner/

# Temp files
tmp_test_*.pym
demo-trigger.py
load.vim

# Old review notes
_review_notes/
```

**Acceptance criteria:** No temp files at root. `.gitignore` covers all dev/runtime artifacts. Commit cleanly.

---

## Phase 2: Reorganization (Moves)

### 2.1 Move root-level docs to `docs/`
```
mv EVENT_BASED_DEMO_PLAN.md docs/plans/
mv EVENT_BASED_PHASE_1_CODE_REVIEW.md docs/reviews/  # (create dir)
mv EVENT_BASED_TEST_PLAN.md docs/plans/
mv EventBased_Demo.md docs/
mv HOW_TO_USE_REMORA.md docs/
mv CUSTOM_NVIM_DEVENV_GUIDE.md docs/
mv CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md docs/
mv REPO_CLEANUP_ANALYSIS.md docs/
```

### 2.2 Move concept docs from `examples/` to `docs/concepts/`
```
mkdir -p docs/concepts
mv examples/*_CONCEPT.md docs/concepts/
mv examples/COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE.md docs/concepts/
```

### 2.3 Deduplicate training examples
Keep `docs/training_examples/`, remove `scripts/training_examples/` (already gitignored).

### 2.4 Archive old plans
```
mkdir -p docs/plans/archive
mv docs/plans/2026-02-26-*.md docs/plans/archive/
mv docs/plans/2026-02-27-*.md docs/plans/archive/
```

### 2.5 Delete old report
```
rm docs/reports/cairn_test_coverage.md
rmdir docs/reports/
```

**Acceptance criteria:** Root has only config files + `README.md`. Docs organized into `docs/`, `docs/plans/`, `docs/reviews/`, `docs/concepts/`. No duplicates.

---

## Phase 3: Option A Completion (Code Modifications)

> **Note:** Option A LSP migration is COMPLETE (see `.scratch/projects/option-a-unification/`). These items from the original analysis may already be done. Verify before acting.

### 3.1 Verify LSP `__init__.py` exports are correct
### 3.2 Verify LSP handlers use `AgentNode` from EventStore
### 3.3 Delete `core/agent_state.py` if no remaining references
### 3.4 Delete `core/swarm_state.py` if no remaining references
### 3.5 Update tests for deleted modules

**Acceptance criteria:** No broken imports. All tests pass. No references to deleted types.

---

## Phase 4: Documentation Refresh

### 4.1 Rewrite `docs/ARCHITECTURE.md` for EventBased
### 4.2 Update `docs/CONCEPT.md` (pyproject.toml readme)
### 4.3 Rewrite `docs/HOW_TO_CREATE_AN_AGENT.md` for AgentExtension
### 4.4 Update `docs/API_REFERENCE.md`
### 4.5 Update `README.md`

**Acceptance criteria:** All docs describe the EventBased architecture, not the old one.

---

## Dependencies

- Phase 1 has no dependencies. Can start immediately.
- Phase 2 has no dependencies. Can run in parallel with Phase 1.
- Phase 3 depends on verifying Option A completion status.
- Phase 4 depends on Phase 3 (docs should describe final code state).
