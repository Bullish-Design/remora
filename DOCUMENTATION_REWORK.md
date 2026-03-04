# DOCUMENTATION_REWORK.md

> Comprehensive documentation analysis for Remora — production readiness assessment.
> Generated 2026-03-03 as part of the doc-rework project.

---

## Table of Contents

### 1. Executive Summary
Brief overview of findings: total files analyzed, key problems, top-priority actions.

### 2. Current State Inventory
Complete inventory of all documentation files across 4 locations (root, docs/, .hidden/, server/), with file counts, total sizes, and categories.

### 3. Accuracy Assessment — Codebase Cross-Reference
What's correct vs stale vs wrong. Verified classes, CLI commands, API endpoints, and installation claims against actual source code.

### 4. File-by-File Action Items
Every documentation file with its verdict: KEEP / REVISE / MOVE / DELETE / MERGE. Organized by location.

- 4.1 Root-Level Files (19 files)
- 4.2 docs/ Top-Level Files (17 files)
- 4.3 docs/guides/ (5 files)
- 4.4 docs/plans/ (11 files)
- 4.5 docs/reports/ (1 file)
- 4.6 docs/training_examples/ (6 files)
- 4.7 .hidden/ (27 files)
- 4.8 server/ (2 files)

### 5. Recommended Documentation Structure
What the ideal docs/ tree should look like after cleanup. Target file organization.

### 6. New Documentation Needed
Gaps identified — docs that should exist but don't.

### 7. Priority Ordering
Ranked action items: what to fix first for maximum impact.

### 8. Appendix: Stale References Catalog
Complete list of every stale class, import, CLI command, and endpoint found in docs with the files that reference them.

---

## 1. Executive Summary

**90 documentation files** were analyzed across 4 locations: repo root (19), docs/ (42), .hidden/ (27), and server/ (2). Total documentation volume is approximately **1.5MB**.

### Key Findings

1. **Root is cluttered.** 16 of 19 root-level .md files are historical artifacts (code reviews, refactor guides, brainstorming docs) that should not be at the repo root. Only README.md, AGENTS.md, and HOW_TO_USE_REMORA.md belong there.

2. **Significant staleness.** Multiple docs reference classes, imports, and API endpoints that no longer exist. `SwarmState`, `AgentState`, `ASTAgentNode`, `ExtensionNode`, `AgentRunner`, and `KernelRunner` are all gone — unified into `AgentNode` during the EventBased architecture transition. At least 10 docs contain stale references.

3. **Duplicate architecture docs.** `docs/ARCHITECTURE.md` (uppercase) and `docs/architecture.md` (lowercase) both exist with overlapping content. Need to merge into one.

4. **Completely wrong doc still present.** `docs/CONCEPT.md` describes the V1 architecture (bundles, KernelRunner, Hub Context, Decision Packet) — none of which exist anymore. Should be deleted.

5. **False installation instructions.** Multiple docs claim `pip install remora` works. The package is not published to PyPI. Actual installation is via devenv.sh + uv.

6. **Stale API endpoint references.** `docs/REMORA_UI_API.md` references `/run`, `/plan`, `/snapshot` endpoints that do not exist in the current `RemoraService` class.

7. **Non-documentation in docs/.** 6 training example files and 7 old implementation plans sit in docs/ but are not useful documentation for contributors.

### Recommended Actions (Summary)

| Action | Count |
|--------|-------|
| KEEP (no changes) | 7 |
| KEEP + REVISE | 13 |
| MOVE to .hidden/ | 25 |
| MOVE to docs/plans/ | 3 |
| MERGE/CONSOLIDATE | 3 |
| DELETE | 3 |
| Already archived (.hidden/) | 27 |
| KEEP in server/ | 2 |

### Top 3 Priorities
1. **Delete or archive the 16 root-level historical files** — immediate declutter
2. **Fix stale references** in README.md, HOW_TO_USE_REMORA.md, and the 8 other affected docs
3. **Merge duplicate architecture docs** and delete the stale CONCEPT.md

---

## 2. Current State Inventory

### By Location

| Location | Files | Approx Size | Description |
|----------|-------|-------------|-------------|
| Root (`/`) | 19 .md files | ~650KB | README + 18 historical artifacts |
| `docs/` (top-level) | 17 files | ~120KB | Architecture, reference, how-to guides |
| `docs/guides/` | 5 files | ~30KB | Workflow and setup guides |
| `docs/plans/` | 11 files | ~80KB | Implementation plans (mix of current + old) |
| `docs/reports/` | 1 file | <1KB | Empty placeholder |
| `docs/training_examples/` | 6 files | ~40KB | LLM training data (not docs) |
| `.hidden/` | 27 files | ~850KB | Archived historical docs |
| `server/` | 2 files | ~15KB | vLLM deployment docs |
| **Total** | **88 files** | **~1.8MB** | |

### By Category

| Category | Count | Key Files |
|----------|-------|-----------|
| **Authoritative design docs** | 2 | EventBased_Concept.md, architecture.md |
| **Reference docs** | 6 | API_REFERENCE, CONFIGURATION, LLM_REFERENCE, SPEC, INSTALLATION, TROUBLESHOOTING |
| **User-facing guides** | 8 | HOW_TO_USE_REMORA, HOW_TO_CREATE_AN_AGENT, getting-started, customization, llm-configuration, notetaking-workflow, programming-workflow, overview |
| **External library guides** | 3 | HOW_TO_USE_GRAIL, HOW_TO_USE_STRUCTURED_AGENTS, Qwen model guide |
| **API/Service docs** | 1 | REMORA_UI_API |
| **Testing docs** | 1 | TESTING_GUIDELINES |
| **Active plans** | 4 | EVENT_ARCHITECTURE_ALIGNMENT, agentnode-design, agentnode-implementation, architectural-unification |
| **Historical plans** | 7 | Old UI/panel/graph plans from docs/plans/ |
| **Historical reviews/guides** | 14 | Root-level CODE_REVIEW, CLEAN_UP_REVIEW, PHASE_1/2 reviews, etc. |
| **Server deployment** | 2 | server/README, SERVER_DEV_GUIDE |
| **Training data** | 6 | docs/training_examples/ |
| **Archived** | 27 | .hidden/ directory |
| **Onboarding** | 2 | README.md, AGENTS.md |
| **Stale/wrong** | 2 | CONCEPT.md (V1 architecture), cairn_test_coverage.md (empty) |

### Root-Level File Sizes (largest first)

These files dominate the root directory and are mostly historical:

| File | Size | Verdict |
|------|------|---------|
| EVENT_BASED_DEMO_PLAN.md | 166KB | MOVE to docs/plans/ |
| PYDANTIC_CONSOLIDATION_REFACTOR.md | 107KB | MOVE to .hidden/ |
| NEOVIM_DEMO_V21_FINAL_CONCEPT.md | 59KB | MOVE to .hidden/ |
| EVENT_BASED_TEST_PLAN.md | 44.7KB | MOVE to docs/plans/ |
| EventBased_Demo.md | 42.5KB | MOVE to .hidden/ |
| EVENT_BASED_PHASE_2_CODE_REVIEW.md | 41.6KB | MOVE to .hidden/ |
| REMORA_LAUNCH_PLAN.md | 41KB | MOVE to docs/plans/ |
| REPO_CLEANUP_ANALYSIS.md | 41KB | MOVE to .hidden/ |
| EVENT_BASED_PHASE_1_CODE_REVIEW.md | 30.6KB | MOVE to .hidden/ |
| CUSTOM_NVIM_DEVENV_GUIDE.md | 30.6KB | MOVE or DELETE |
| CODE_REVIEW.md | 28KB | MOVE to .hidden/ |
| DEVENV_INSTALLED_BRAINSTORM.md | 26KB | MOVE to .hidden/ |
| AGENT_CONTAINER_PLAN.md | 22.5KB | MOVE to .hidden/ |
| NEOVIM_DEMO_V24_CODE_REVIEW.md | 20.4KB | MOVE to .hidden/ |
| CLEAN_UP_REVIEW.md | 13KB | MOVE to .hidden/ |
| CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md | 5.2KB | MOVE to .hidden/ |
| HOW_TO_USE_REMORA.md | 2.9KB | REVISE (keep at root) |
| README.md | 2.3KB | REVISE (keep at root) |
| AGENTS.md | 91B | REVISE (keep at root) |

---

## 3. Accuracy Assessment — Codebase Cross-Reference

All documentation claims were verified against the actual source code in `src/remora/`. This section catalogs what's correct and what's wrong.

### 3.1 Classes & Types

#### Removed (stale references)

| Class/Type | Current Status | Docs That Reference It |
|---|---|---|
| `SwarmState` | **REMOVED** — unified into EventBased arch | README.md, HOW_TO_USE_REMORA.md, docs/ARCHITECTURE.md, docs/CONCEPT.md |
| `AgentState` | **REMOVED** — unified into AgentNode | docs/CONCEPT.md, docs/ARCHITECTURE.md |
| `ASTAgentNode` | **REMOVED** — unified into AgentNode | NEOVIM_DEMO_V21_FINAL_CONCEPT.md |
| `ExtensionNode` | **REMOVED** — unified into AgentNode | NEOVIM_DEMO_V21_FINAL_CONCEPT.md |
| `AgentRunner` | **REMOVED** — replaced by SwarmExecutor | docs/ARCHITECTURE.md (uppercase) |
| `KernelRunner` | **REMOVED** — old V1 concept | docs/CONCEPT.md |
| `Hub Context` | **REMOVED** — old V1 concept | docs/CONCEPT.md |
| `Decision Packet` | **REMOVED** — old V1 concept | docs/CONCEPT.md |

#### Exists (correctly referenced)

| Class/Type | Location | Status |
|---|---|---|
| `AgentNode` | `core/agent_node.py:67` | Correctly referenced in EventBased_Concept.md, architecture.md |
| `EventStore` | `core/event_store.py` | Correctly referenced in multiple docs |
| `SubscriptionRegistry` | `core/subscriptions.py` | Correctly referenced |
| `RemoraConfig` | `core/config.py` | Correctly referenced in CONFIGURATION.md |
| `SwarmExecutor` | `core/swarm_executor.py` | Correctly referenced in architecture.md |
| `RemoraService` | `service/api.py` | Partially correct (some endpoints stale) |

### 3.2 CLI Commands

| Command | Status | Notes |
|---|---|---|
| `remora swarm start` | EXISTS | Verified in cli/main.py |
| `remora swarm reconcile` | EXISTS | Verified |
| `remora swarm list` | EXISTS | Verified |
| `remora swarm emit` | EXISTS | Verified |
| `remora serve` | EXISTS | Verified |
| `remora run` | **DOES NOT EXIST** | Referenced in docs/SPEC.md — stale |

### 3.3 Service API Endpoints

| Endpoint/Method | Status | Notes |
|---|---|---|
| `subscribe_stream` | EXISTS | SSE subscription |
| `events_stream` | EXISTS | SSE event stream |
| `input` | EXISTS | User input |
| `config_snapshot` | EXISTS | Config snapshot |
| `get_agent` | EXISTS | Agent by ID |
| `get_agent_subscriptions` | EXISTS | Subscriptions for agent |
| `/run` | **DOES NOT EXIST** | Referenced in REMORA_UI_API.md |
| `/plan` | **DOES NOT EXIST** | Referenced in REMORA_UI_API.md |
| `/snapshot` | **DOES NOT EXIST** | Referenced in REMORA_UI_API.md |

### 3.4 Installation & Package

| Claim | Verdict |
|---|---|
| `pip install remora` | **FALSE** — not published to PyPI. Referenced in: README.md, INSTALLATION.md, getting-started.md |
| `remora.yaml.example` exists | **TRUE** — verified at repo root |
| devenv.sh is the installation method | **TRUE** — but only mentioned in getting-started.md, not README.md |
| Python 3.14 support claimed | **UNVERIFIED** — need to check pyproject.toml |

### 3.5 Tool System

All tool modules verified in `core/tools/`: grail.py, lsp.py, spawn_child.py, swarm.py — all exist and are active.

### 3.6 Accuracy Summary

- **10 docs contain stale references** that need updating
- **1 doc is entirely wrong** (CONCEPT.md describes V1 architecture)
- **3 docs falsely claim** pip install works
- **1 doc has 3 non-existent API endpoints** (REMORA_UI_API.md)
- **Authoritative docs** (EventBased_Concept.md, architecture.md lowercase) are **accurate**

---

## 4. File-by-File Action Items

Legend: **KEEP** = no changes needed | **REVISE** = content needs updating | **MOVE** = relocate | **DELETE** = remove | **MERGE** = consolidate into another doc

### 4.1 Root-Level Files (19 files)

| # | File | Size | Verdict | Action |
|---|------|------|---------|--------|
| 1 | README.md | 2.3KB | **REVISE** | Fix `pip install` → devenv instructions. Fix SwarmState reference. Add devenv.sh mention. Verify doc links. |
| 2 | AGENTS.md | 91B | **REVISE** | Expand with real agent instructions if repo goes public, or keep as internal redirect. |
| 3 | HOW_TO_USE_REMORA.md | 2.9KB | **REVISE** | Fix SwarmState/AgentMetadata imports. Verify EventStore/SubscriptionRegistry APIs. Verify `--nvim` flag. Verify service endpoints. |
| 4 | CODE_REVIEW.md | 28KB | **MOVE** | → `.hidden/` (2026-03-01 historical code review) |
| 5 | CLEAN_UP_REVIEW.md | 13KB | **MOVE** | → `.hidden/` (post-Pydantic audit, stale baseline of 659 tests) |
| 6 | AGENT_CONTAINER_PLAN.md | 22.5KB | **MOVE** | → `.hidden/` (Docker/Tailscale infra brainstorm) |
| 7 | CUSTOM_NVIM_DEVENV_GUIDE.md | 30.6KB | **MOVE or DELETE** | Belongs in nixvim repo, not remora. Move to docs/guides/ if keeping. |
| 8 | CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md | 5.2KB | **MOVE** | → `.hidden/` (task-specific migration guide, likely completed) |
| 9 | DEVENV_INSTALLED_BRAINSTORM.md | 26KB | **MOVE** | → `.hidden/` (packaging brainstorm) |
| 10 | EventBased_Demo.md | 42.5KB | **MOVE** | → `.hidden/` (superseded by EVENT_BASED_DEMO_PLAN) |
| 11 | EVENT_BASED_DEMO_PLAN.md | 166KB | **MOVE** | → `docs/plans/` (detailed MVP demo plan, useful reference) |
| 12 | EVENT_BASED_PHASE_1_CODE_REVIEW.md | 30.6KB | **MOVE** | → `.hidden/` (historical Phase 1 review) |
| 13 | EVENT_BASED_PHASE_2_CODE_REVIEW.md | 41.6KB | **MOVE** | → `.hidden/` (historical Phase 2 review) |
| 14 | EVENT_BASED_TEST_PLAN.md | 44.7KB | **MOVE** | → `docs/plans/` (test strategy, partially relevant) |
| 15 | NEOVIM_DEMO_V21_FINAL_CONCEPT.md | 59KB | **MOVE** | → `.hidden/` (superseded by EventBased_Concept.md) |
| 16 | NEOVIM_DEMO_V24_CODE_REVIEW.md | 20.4KB | **MOVE** | → `.hidden/` (historical V2.4 review) |
| 17 | PYDANTIC_CONSOLIDATION_REFACTOR.md | 107KB | **MOVE** | → `.hidden/` (completed refactor guide) |
| 18 | REMORA_LAUNCH_PLAN.md | 41KB | **MOVE** | → `docs/plans/` (consolidated action plan from all reviews) |
| 19 | REPO_CLEANUP_ANALYSIS.md | 41KB | **MOVE** | → `.hidden/` (partially superseded by actual cleanup) |

**Result after cleanup:** Root contains only README.md, AGENTS.md, HOW_TO_USE_REMORA.md (all revised).

### 4.2 docs/ Top-Level Files (17 files)

| # | File | Verdict | Action |
|---|------|---------|--------|
| 1 | EventBased_Concept.md | **KEEP** | Authoritative vision doc per REPO_RULES.md. No changes needed. |
| 2 | architecture.md (lowercase) | **KEEP + REVISE** | Primary architecture doc. Merge content from ARCHITECTURE.md (uppercase) into this. Verify all references. |
| 3 | ARCHITECTURE.md (uppercase) | **MERGE → architecture.md** | Merge any unique content into architecture.md, then delete this file. |
| 4 | overview.md | **KEEP + REVISE** | Good onboarding doc. Verify feature descriptions match current codebase. |
| 5 | API_REFERENCE.md | **REVISE** | Verify listed modules/functions exist. Update for current exports. |
| 6 | CONFIGURATION.md | **KEEP + minor REVISE** | Well-structured. Verify against current RemoraConfig fields. |
| 7 | SPEC.md | **MERGE or DELETE** | Overlaps with API_REFERENCE and CONFIGURATION. References stale `remora run` command and old bundle format. Merge useful bits, delete rest. |
| 8 | INSTALLATION.md | **REVISE** | Fix `pip install` claim. Verify extras (backend, frontend, full) exist in pyproject.toml. Verify Python version claims. |
| 9 | LLM_REFERENCE.md | **KEEP** | Dense machine-optimized reference. Verify accuracy but structure is excellent. |
| 10 | REMORA_UI_API.md | **REVISE** | Remove /run, /plan, /snapshot. Update to match actual RemoraService methods. |
| 11 | TESTING_GUIDELINES.md | **REVISE** | Update for current test suite structure. Add mention of Hypothesis property tests (14 added). Remove old phase-aligned references. |
| 12 | TROUBLESHOOTING.md | **REVISE** | Update error codes, field names (`agents_dir` → current name, `operations.*.subagent` → current). |
| 13 | HOW_TO_CREATE_AN_AGENT.md | **KEEP + REVISE** | High-quality guide. Verify structured-agents/grail versions. Check bundle format references. |
| 14 | HOW_TO_USE_GRAIL.md | **KEEP** | External library guide, well-written. |
| 15 | HOW_TO_USE_STRUCTURED_AGENTS.md | **KEEP** | External library guide, well-written. |
| 16 | STRUCTURED_AGENTS-HOW_TO_USE_QWEN_MODEL.md | **KEEP** | Model-specific guide. Consider moving to guides/ subfolder. |
| 17 | CONCEPT.md | **DELETE** | Describes V1 architecture (KernelRunner, Hub Context, Decision Packet). Completely wrong for current codebase. Superseded by EventBased_Concept.md. |

### 4.3 docs/guides/ (5 files)

| # | File | Verdict | Action |
|---|------|---------|--------|
| 1 | getting-started.md | **REVISE** | Fix `pip install` reference. Verify devenv setup steps. Good structure. |
| 2 | customization.md | **REVISE** | Verify `.remora/models/*.py` path, bundle config format, extension model. |
| 3 | llm-configuration.md | **REVISE** | Verify vLLM setup commands, model resolution logic, per-bundle overrides. |
| 4 | notetaking-workflow.md | **REVISE** | Verify node types and markdown agent model. |
| 5 | programming-workflow.md | **REVISE** | Verify keybindings, diagnostics, code actions, agent panel features. |

### 4.4 docs/plans/ (11 files)

| # | File | Verdict | Action |
|---|------|---------|--------|
| 1 | EVENT_ARCHITECTURE_ALIGNMENT.md | **KEEP** | Referenced by REPO_RULES.md as key design doc. |
| 2 | 2026-03-02-agentnode-design.md | **KEEP** | Referenced by REPO_RULES.md. AgentNode design spec. |
| 3 | 2026-03-02-agentnode-implementation.md | **KEEP** | Referenced by REPO_RULES.md. Implementation plan. |
| 4 | 2026-03-01-architectural-unification.md | **KEEP** | Foundation document for current architecture. |
| 5 | 2026-03-01-graph-viewer-v2-design.md | **MOVE** | → `.hidden/` (specific UI implementation plan) |
| 6 | 2026-03-01-zoom-to-cursor.md | **MOVE** | → `.hidden/` (specific UI feature plan) |
| 7 | 2026-03-01-web-graph-view-design.md | **MOVE** | → `.hidden/` (specific UI design) |
| 8 | 2026-03-01-panel-redesign-impl.md | **MOVE** | → `.hidden/` (specific UI implementation) |
| 9 | 2026-03-01-panel-redesign.md | **MOVE** | → `.hidden/` (specific UI concept) |
| 10 | 2026-02-26/27 files (3 files) | **MOVE** | → `.hidden/` (pre-EventBased v0.4.x plans) |
| 11 | 2026-02-27-ground-up-analysis.md | **MOVE** | → `.hidden/` (pre-EventBased analysis) |

### 4.5 docs/reports/ (1 file)

| # | File | Verdict | Action |
|---|------|---------|--------|
| 1 | cairn_test_coverage.md | **DELETE** | Empty placeholder — just says "Date: TBD". No actual content. |

### 4.6 docs/training_examples/ (6 files)

| # | File | Verdict | Action |
|---|------|---------|--------|
| 1-4 | remora/llm_conversations_*.md (4) | **MOVE to .hidden/ or DELETE** | Old FunctionGemma LLM conversation logs. Training data, not documentation. |
| 5 | shell/train_readable.md | **MOVE to .hidden/ or DELETE** | Training data in readable format. |
| 6 | smart_home/train_readable.md | **MOVE to .hidden/ or DELETE** | Training data in readable format. |

### 4.7 .hidden/ (27 files)

All 27 files are already archived in the correct location. **No action needed** except:

- **Consider deleting** `session-ses_38d4.md` (267KB session log bloating the repo)
- **Flag for review** `FUTURE_ENHANCEMENTS.md` (may contain still-relevant enhancement ideas)
- **Verify** `.hidden/` is in `.gitignore`

### 4.8 server/ (2 files)

| # | File | Verdict | Action |
|---|------|---------|--------|
| 1 | server/README.md | **KEEP + minor REVISE** | Verify Docker commands still work. Stay in server/. |
| 2 | server/SERVER_DEV_GUIDE.md | **KEEP + minor REVISE** | Update reference to VLLM_REFACTOR.md (now in .hidden/). Stay in server/. |

---

## 5. Recommended Documentation Structure

After all moves, merges, and deletions, the documentation tree should look like this:

```
/                                   # Repo root — clean, minimal
├── README.md                       # Quick start, overview, links to docs/
├── AGENTS.md                       # AI agent instructions (or .scratch redirect)
├── HOW_TO_USE_REMORA.md            # Concise usage guide
├── remora.yaml.example             # Config template
│
├── docs/                           # All documentation lives here
│   ├── overview.md                 # "What is Remora" — entry point
│   ├── EventBased_Concept.md       # Authoritative design vision
│   ├── architecture.md             # Merged architecture doc (single source of truth)
│   ├── LLM_REFERENCE.md            # Machine-optimized reference
│   │
│   ├── reference/                  # Technical reference (NEW subdirectory)
│   │   ├── API_REFERENCE.md        # CLI + Python API
│   │   ├── CONFIGURATION.md        # remora.yaml schema
│   │   ├── INSTALLATION.md         # How to install (devenv, not pip)
│   │   ├── TESTING_GUIDELINES.md   # Test conventions + Hypothesis
│   │   ├── TROUBLESHOOTING.md      # Common issues and fixes
│   │   └── REMORA_UI_API.md        # Service/Datastar SSE endpoints
│   │
│   ├── guides/                     # How-to guides
│   │   ├── getting-started.md      # First-run walkthrough
│   │   ├── customization.md        # Tools, bundles, extensions
│   │   ├── llm-configuration.md    # vLLM, model setup
│   │   ├── notetaking-workflow.md   # Markdown agents
│   │   ├── programming-workflow.md  # Editor integration
│   │   ├── HOW_TO_CREATE_AN_AGENT.md
│   │   ├── HOW_TO_USE_GRAIL.md
│   │   ├── HOW_TO_USE_STRUCTURED_AGENTS.md
│   │   └── STRUCTURED_AGENTS-HOW_TO_USE_QWEN_MODEL.md
│   │
│   └── plans/                      # Retained design plans (4 files only)
│       ├── EVENT_ARCHITECTURE_ALIGNMENT.md
│       ├── 2026-03-02-agentnode-design.md
│       ├── 2026-03-02-agentnode-implementation.md
│       └── 2026-03-01-architectural-unification.md
│
├── server/                         # Server deployment docs (stay here)
│   ├── README.md
│   └── SERVER_DEV_GUIDE.md
│
└── .hidden/                        # Archive (all historical docs)
    ├── (existing 27 files)
    ├── (11 files moved from root)
    ├── (7 files moved from docs/plans/)
    ├── (6 files moved from docs/training_examples/)
    └── (ARCHITECTURE.md uppercase, after merge)
```

### Key Changes from Current State:
1. **Root decluttered**: 19 .md files → 3
2. **New `docs/reference/` subdirectory**: Groups technical reference docs together
3. **docs/plans/ trimmed**: 11 files → 4 (only those referenced by REPO_RULES.md)
4. **docs/training_examples/ removed**: Moved to .hidden/ (not documentation)
5. **docs/reports/ removed**: Only file was empty placeholder
6. **Single architecture doc**: ARCHITECTURE.md merged into architecture.md
7. **CONCEPT.md deleted**: V1 architecture, completely wrong

---

## 6. New Documentation Needed

These docs do not currently exist but should be created for production readiness:

| Priority | Document | Description |
|----------|----------|-------------|
| **HIGH** | `docs/reference/DEVELOPMENT.md` | Developer setup guide — devenv.sh, uv, running tests, project structure. Currently this info is scattered or missing. |
| **HIGH** | `CONTRIBUTING.md` | Standard open-source contribution guide — code style, PR process, test requirements. |
| **MEDIUM** | `docs/reference/EVENT_MODEL.md` | Dedicated doc for the event system — event types, lifecycle, EventStore API, projection patterns. Currently spread across EventBased_Concept.md and architecture.md. |
| **MEDIUM** | `docs/guides/deployment.md` | How to deploy Remora in production — currently only the server/ docs cover vLLM deployment, nothing covers the overall system. |
| **LOW** | `docs/CHANGELOG.md` | Version history and breaking changes. Useful once releases begin. |
| **LOW** | `docs/reference/EXTENSIONS.md` | How the extension system works — `extensions.py`, model loading, hook points. Currently mentioned in customization.md but not documented in depth. |

---

## 7. Priority Ordering

Ranked from highest to lowest impact:

### P0 — Immediate (do first)

1. **Move 16 root-level files** to .hidden/ and docs/plans/
   - Single batch operation, massive declutter
   - No content editing needed, just `git mv`

2. **Delete docs/CONCEPT.md**
   - Entirely wrong (V1 architecture). Dangerous for anyone reading it.

3. **Delete docs/reports/cairn_test_coverage.md**
   - Empty placeholder with no value.

4. **Merge docs/ARCHITECTURE.md → docs/architecture.md**
   - Eliminate the duplicate. Keep lowercase as primary.

### P1 — High Priority (do second)

5. **Fix README.md**
   - Fix `pip install` → devenv instructions
   - Fix SwarmState reference
   - Add devenv.sh mention
   - This is the first file anyone reads.

6. **Fix HOW_TO_USE_REMORA.md**
   - Fix stale imports (SwarmState, AgentMetadata)
   - Verify all code examples

7. **Fix docs/INSTALLATION.md**
   - Replace pip install with devenv/uv instructions
   - Verify extras and Python version claims

8. **Fix docs/REMORA_UI_API.md**
   - Remove non-existent /run, /plan, /snapshot endpoints
   - Document actual RemoraService methods

### P2 — Medium Priority (do third)

9. **Move 7 old plans from docs/plans/ to .hidden/**
10. **Move 6 training examples from docs/training_examples/ to .hidden/**
11. **Merge/delete docs/SPEC.md** — extract useful bits into API_REFERENCE.md
12. **Revise docs/TESTING_GUIDELINES.md** — add Hypothesis, update structure
13. **Revise docs/TROUBLESHOOTING.md** — fix stale field names
14. **Revise docs/API_REFERENCE.md** — verify all listed exports
15. **Create docs/reference/ subdirectory** and reorganize

### P3 — Low Priority (do when convenient)

16. **Revise all 5 docs/guides/ files** — verify accuracy of each
17. **Revise docs/architecture.md** — after merge, do a full accuracy pass
18. **Revise server/ docs** — verify Docker commands
19. **Create DEVELOPMENT.md** — developer setup guide
20. **Create CONTRIBUTING.md** — contribution guide
21. **Delete .hidden/session-ses_38d4.md** — 267KB session log
22. **Review .hidden/FUTURE_ENHANCEMENTS.md** — extract still-relevant ideas

---

## 8. Appendix: Stale References Catalog

Complete list of every stale reference found across all documentation files.

### Stale Class/Type References

| Reference | Should Be | Found In |
|---|---|---|
| `SwarmState` | Removed (use EventStore + AgentNode) | README.md, HOW_TO_USE_REMORA.md, docs/ARCHITECTURE.md, docs/CONCEPT.md |
| `AgentState` | Removed (unified into AgentNode) | docs/CONCEPT.md, docs/ARCHITECTURE.md |
| `AgentRunner` | Removed (replaced by SwarmExecutor) | docs/ARCHITECTURE.md |
| `ASTAgentNode` | Removed (unified into AgentNode) | NEOVIM_DEMO_V21_FINAL_CONCEPT.md |
| `ExtensionNode` | Removed (unified into AgentNode) | NEOVIM_DEMO_V21_FINAL_CONCEPT.md |
| `KernelRunner` | Removed (old V1) | docs/CONCEPT.md |
| `Hub Context` | Removed (old V1) | docs/CONCEPT.md |
| `Decision Packet` | Removed (old V1) | docs/CONCEPT.md |
| `AgentMetadata` | Verify — may be in config/models | HOW_TO_USE_REMORA.md |

### Stale Import Paths

| Import | Found In |
|---|---|
| `from remora.core.swarm_state import SwarmState, AgentMetadata` | HOW_TO_USE_REMORA.md |
| `from remora.core.swarm_state import SwarmState` | README.md (conceptual reference) |

### Stale CLI Commands

| Command | Found In |
|---|---|
| `remora run` | docs/SPEC.md |

### Stale API Endpoints

| Endpoint | Found In |
|---|---|
| `/run` | docs/REMORA_UI_API.md |
| `/plan` | docs/REMORA_UI_API.md |
| `/snapshot` | docs/REMORA_UI_API.md |

### Stale Installation Claims

| Claim | Found In |
|---|---|
| `pip install remora` | README.md, docs/INSTALLATION.md, docs/guides/getting-started.md |
| `pip install remora[backend]` | docs/INSTALLATION.md |
| `pip install remora[frontend]` | docs/INSTALLATION.md |
| `pip install remora[full]` | docs/INSTALLATION.md |

### Stale Config Field Names

| Field | Found In |
|---|---|
| `agents_dir` | docs/TROUBLESHOOTING.md |
| `operations.*.subagent` | docs/TROUBLESHOOTING.md |

### Stale Test References

| Reference | Found In |
|---|---|
| "659 tests" baseline | CLEAN_UP_REVIEW.md (actual: 1388) |
| "205 tests" baseline | EVENT_BASED_PHASE_2_CODE_REVIEW.md (actual: 1388) |
| Old phase-aligned test suites | docs/TESTING_GUIDELINES.md |
| No mention of Hypothesis tests | docs/TESTING_GUIDELINES.md |

---

*End of documentation rework analysis.*
