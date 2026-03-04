# Root-Level .md File Analysis

## Summary

19 root-level .md files totaling ~650KB. Most are one-off review/plan documents from the
development process that should NOT live at the repo root. Only README.md belongs at root level.

---

## File-by-File Assessment

### 1. README.md (69 lines, 2.3KB) — **REVISE**
- **Content**: Quick start, swarm model, CLI commands, config, installation, docs links
- **Issues**:
  - `pip install remora` — is this actually published to PyPI? Unlikely. Should reference devenv/uv.
  - References `remora.yaml.example` — does this file exist?
  - `SwarmState` referenced in Swarm Model section — may be outdated (post-unification)
  - Links to `docs/ARCHITECTURE.md` and `docs/CONFIGURATION.md` — verify these are accurate
  - No mention of devenv.sh, the actual development workflow
- **Verdict**: REVISE — accurate structure but details need updating for current codebase

### 2. AGENTS.md (3 lines, 91B) — **REVISE**
- **Content**: Just says "read .scratch/CRITICAL_RULES.md"
- **Issues**: AGENTS.md is a standard convention for AI coding tools. The .scratch redirect is
  fine for dev, but if repo goes public this file should have real content.
- **Verdict**: REVISE — expand with real agent instructions or keep as internal redirect

### 3. HOW_TO_USE_REMORA.md (145 lines, 2.9KB) — **REVISE**
- **Content**: Quick start, core concepts (EventStore, SubscriptionRegistry, SwarmState), service API, Neovim integration
- **Issues**:
  - `from remora.core.swarm_state import SwarmState, AgentMetadata` — SwarmState may be stale
  - `from remora.core.event_store import EventStore` — verify API matches current code
  - `from remora.core.subscriptions import SubscriptionRegistry, SubscriptionPattern` — verify
  - Service API endpoints listed — verify against actual service code
  - `remora swarm start --nvim` — verify this CLI flag exists
- **Cross-ref needed**: All imports and CLI commands need verification against current code
- **Verdict**: REVISE — useful structure but needs comprehensive accuracy check

### 4. CODE_REVIEW.md (447 lines, 28KB) — **MOVE to .hidden/**
- **Content**: Comprehensive code review from 2026-03-01 against V2.1 concept
- **Issues**: Historical review document. Many findings likely addressed in subsequent work.
  Not useful for new contributors.
- **Verdict**: MOVE to .hidden/ — historical artifact, superseded by later reviews

### 5. CLEAN_UP_REVIEW.md (340 lines, 13KB) — **MOVE to .hidden/**
- **Content**: Post-Pydantic-consolidation audit from 2026-03-02. References 659 tests (now 1388).
- **Issues**: Stale baseline numbers. Lists issues that may be fixed. Historical audit.
- **Verdict**: MOVE to .hidden/ — historical artifact

### 6. AGENT_CONTAINER_PLAN.md (22.5KB) — **MOVE to .hidden/**
- **Content**: Docker/Tailscale agent container plan. Infrastructure doc for containerized deployment.
- **Issues**: Not Remora-specific documentation. Infrastructure brainstorming. Doesn't belong at root.
- **Verdict**: MOVE to .hidden/ — future infra planning, not relevant to library docs

### 7. CUSTOM_NVIM_DEVENV_GUIDE.md (30.6KB) — **MOVE**
- **Content**: Guide for importing nv2 (custom Neovim) into devenv projects.
- **Issues**: This is about the nixvim project, not Remora. It's useful but belongs in the
  nixvim repo or in a devenv guides folder, not at remora root.
- **Verdict**: MOVE to docs/guides/ or DELETE (belongs in nixvim repo)

### 8. CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md (5.2KB) — **MOVE**
- **Content**: Step-by-step guide for refactoring remora_demo to use nv2 devenv.
- **Issues**: Implementation guide for a specific migration task. References remora_demo which
  may or may not still exist in current form.
- **Verdict**: MOVE to .hidden/ — task-specific guide, likely completed or obsolete

### 9. DEVENV_INSTALLED_BRAINSTORM.md (26KB) — **MOVE to .hidden/**
- **Content**: Brainstorming doc for packaging Remora+Neovim as a devenv module.
- **Issues**: Future brainstorming, not documentation. Still possibly relevant for roadmap but
  doesn't belong at root.
- **Verdict**: MOVE to .hidden/ or docs/plans/ — brainstorming, not actionable docs

### 10. EventBased_Demo.md (42.5KB) — **MOVE to .hidden/**
- **Content**: Brainstorming for demo presentations of EventBased architecture. Explores what
  demos need to accomplish, what exists, gaps, creative approaches.
- **Issues**: Brainstorming document. Superseded by EVENT_BASED_DEMO_PLAN.md (166KB detailed plan).
- **Verdict**: MOVE to .hidden/ — superseded by detailed plan

### 11. EVENT_BASED_DEMO_PLAN.md (166KB!) — **MOVE to docs/plans/**
- **Content**: Massive detailed MVP demo implementation plan. 14 sections covering demo overview,
  sample project, graph viewer architecture, LSP modifications, scripts, etc.
- **Issues**: At 166KB this is the largest file in the repo. Extremely detailed plan document.
  May be partially implemented. Useful reference but WAY too large for root.
- **Verdict**: MOVE to docs/plans/ — keep as reference but get out of root

### 12. EVENT_BASED_PHASE_1_CODE_REVIEW.md (30.6KB) — **MOVE to .hidden/**
- **Content**: Code review of Phase 1 AgentNode implementation (Tasks 1-11).
- **Issues**: Historical code review. Findings likely addressed. Superseded by Phase 2 review.
- **Verdict**: MOVE to .hidden/ — historical artifact

### 13. EVENT_BASED_PHASE_2_CODE_REVIEW.md (41.6KB) — **MOVE to .hidden/**
- **Content**: Comprehensive Phase 2 code review. Executive summary, methodology, architecture
  alignment, findings. References 205 tests (now 1388).
- **Issues**: Historical review. Many findings likely addressed in Close Architecture Gaps and
  Fix Failing Tests projects.
- **Verdict**: MOVE to .hidden/ — historical artifact, valuable reference but not current

### 14. EVENT_BASED_TEST_PLAN.md (44.7KB) — **MOVE to docs/plans/**
- **Content**: Comprehensive test plan covering Phase 1 remediation + full EventBased testing strategy.
  Test philosophy, categories, markers, specific test specs.
- **Issues**: Some content may be implemented already. Testing philosophy and approach are still
  relevant. Could be condensed and moved to docs/TESTING_GUIDELINES.md.
- **Verdict**: MOVE to docs/plans/ or MERGE into docs/TESTING_GUIDELINES.md

### 15. NEOVIM_DEMO_V21_FINAL_CONCEPT.md (59KB) — **MOVE to .hidden/**
- **Content**: Complete rewrite concept for Neovim V2.1 LSP-native architecture. Very detailed
  architecture, Pydantic model layer, ASCII art diagrams.
- **Issues**: Historical concept document. Architecture has evolved past this. References old
  types (ASTAgentNode, ExtensionNode).
- **Verdict**: MOVE to .hidden/ — historical concept, superseded by EventBased_Concept.md

### 16. NEOVIM_DEMO_V24_CODE_REVIEW.md (20.4KB) — **MOVE to .hidden/**
- **Content**: Code review of Neovim Demo V2.4. Covers demo/ and src/remora/lsp/.
  Identifies critical startup crash bug (ThreadDecoratorError), architecture divergences.
- **Issues**: Historical code review. Bug may be fixed. References demo/ directory.
- **Verdict**: MOVE to .hidden/ — historical artifact

### 17. PYDANTIC_CONSOLIDATION_REFACTOR.md (107KB) — **MOVE to .hidden/**
- **Content**: Massive guide for consolidating all Remora types to Pydantic BaseModel.
  9 sections, implementation order, before/after comparisons.
- **Issues**: This refactor was COMPLETED (per CLEAN_UP_REVIEW.md baseline). The document
  is now historical. At 107KB it's a huge root-level file with no current utility.
- **Verdict**: MOVE to .hidden/ — completed refactor guide

### 18. REMORA_LAUNCH_PLAN.md (41KB) — **MOVE to docs/plans/**
- **Content**: Consolidated action plan from all code reviews. 5 phases: Critical Blockers,
  Architecture Alignment, Dead Code Removal, Testing Gaps, Quality & Polish.
- **Issues**: Key planning document. May be partially completed. References all prior reviews.
  Still relevant for tracking remaining work but belongs in docs/plans/.
- **Verdict**: MOVE to docs/plans/ — active planning doc

### 19. REPO_CLEANUP_ANALYSIS.md (41KB) — **MOVE to .hidden/**
- **Content**: Comprehensive review of every directory/file evaluating applicability to
  EventBased architecture. Classification: KEEP/REMOVE/MODIFY/MOVE.
- **Issues**: Partially superseded by actual cleanup work done. Still useful as reference.
- **Verdict**: MOVE to .hidden/ — reference document for cleanup work

---

## Summary Statistics

| Verdict | Count | Files |
|---------|-------|-------|
| REVISE  | 3     | README.md, AGENTS.md, HOW_TO_USE_REMORA.md |
| MOVE to .hidden/ | 11 | CODE_REVIEW, CLEAN_UP_REVIEW, AGENT_CONTAINER_PLAN, EventBased_Demo, EVENT_BASED_PHASE_1_CODE_REVIEW, EVENT_BASED_PHASE_2_CODE_REVIEW, NEOVIM_DEMO_V21_FINAL_CONCEPT, NEOVIM_DEMO_V24_CODE_REVIEW, PYDANTIC_CONSOLIDATION_REFACTOR, REPO_CLEANUP_ANALYSIS, CUSTOM_NVIM_DEVENV_IMPLEMENTATION |
| MOVE to docs/plans/ | 3 | EVENT_BASED_DEMO_PLAN, REMORA_LAUNCH_PLAN, EVENT_BASED_TEST_PLAN |
| MOVE to docs/guides/ or DELETE | 1 | CUSTOM_NVIM_DEVENV_GUIDE |
| MOVE (brainstorm) | 1 | DEVENV_INSTALLED_BRAINSTORM |

### Root After Cleanup
Only 3 files should remain at root: README.md, AGENTS.md, HOW_TO_USE_REMORA.md (all revised).
