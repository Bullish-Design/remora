# docs/ Directory Analysis

## Summary

42 files across 4 subdirectories. Mix of high-quality current docs (written for the EventBased architecture)
and older/stale docs that predate the current architecture.

---

## Top-Level docs/ Files (17 files)

### KEY REFERENCE DOCS (per REPO_RULES.md)

#### EventBased_Concept.md — **KEEP** (authoritative vision doc)
- Authoritative design document per REPO_RULES.md. Well-written, comprehensive.
- Describes EventLog, events, subscriptions, discovery, reactive loop, AgentNode model.
- 5 perspectives: user, developer, agent, node, environment.
- This is THE canonical document for understanding Remora.

### ARCHITECTURE DOCS (3 files — need consolidation!)

#### ARCHITECTURE.md (uppercase) — **MERGE into architecture.md**
- Shorter overview doc. References SwarmState, AgentRunner, SwarmExecutor, EventBus.
- Decent diagram but somewhat surface-level. Less comprehensive than architecture.md (lowercase).

#### architecture.md (lowercase) — **KEEP as primary, REVISE**
- More detailed doc with proper TOC: System Overview, Discovery, AgentNode, EventStore,
  Events, Subscriptions, Reconciliation, Execution, Extensions, Tools, LSP Layer, Data Flow.
- Well-structured, written for the EventBased architecture.
- Should be the canonical architecture doc. MERGE content from ARCHITECTURE.md into this.

#### overview.md — **KEEP, REVISE**
- User-facing "what is Remora" document. Good for onboarding.
- Covers: what it is, how it works (30-second version), capabilities, concepts, requirements.
- References both programming and notetaking workflows. Links to detailed guides.
- Suitable as the entry point in a docs site.

### REFERENCE DOCS

#### API_REFERENCE.md — **REVISE**
- CLI commands, Python modules reference. Lists core, LSP, workspace, config exports.
- Needs verification that listed modules/functions actually exist.

#### CONFIGURATION.md — **KEEP, minor REVISE**
- Covers remora.yaml schema, env var expansion, field reference.
- Well-structured. Needs verification against current RemoraConfig.

#### SPEC.md — **MERGE or DELETE**
- "Technical Specification" — covers CLI, bundle format, events, API endpoints.
- Overlaps heavily with API_REFERENCE.md and CONFIGURATION.md.
- References `remora run` (is this still a command?), old bundle format, `agents_dir`.
- Some content is stale (references old architecture). MERGE useful bits into other docs.

#### INSTALLATION.md — **REVISE**
- References `pip install remora` — verify this works. References extras: backend, frontend, full.
- Mentions Python 3.14 support — verify.
- Good structure but may reference features/extras that don't exist in pyproject.toml.

#### LLM_REFERENCE.md — **KEEP, verify accuracy**
- Dense machine-optimized reference document. Very comprehensive TOC covering all core components.
- Written for LLM consumption (good for AI-assisted dev).
- Needs accuracy verification but structure is excellent.

#### REMORA_UI_API.md — **REVISE**
- Documents the Datastar SSE service endpoints. Lists /subscribe, /events, /run, /input, etc.
- May be stale — needs verification against actual service/api.py endpoints.

#### TESTING_GUIDELINES.md — **REVISE**
- References "phase-aligned unit suites", event bus, graph builder, context builder.
- References old test structure and concepts. Should be updated to reflect current test suite.
- No mention of Hypothesis tests (we added 14 in the test suite improvement project).

#### TROUBLESHOOTING.md — **REVISE**
- References `remora.errors` error codes, common scenarios.
- References `agents_dir`, `operations.*.subagent` — likely outdated field names.
- Structure is good, content needs updating.

### HOW-TO GUIDES

#### HOW_TO_CREATE_AN_AGENT.md — **KEEP, REVISE**
- Comprehensive guide covering Remora agent model, Grail tools, bundles, events, subscriptions.
- Very detailed with code examples. High quality.
- References structured-agents 0.3.4, grail 3.0.0 — verify versions.
- Some references may be stale (bundle format, tool loading).

#### HOW_TO_USE_GRAIL.md — **KEEP**
- Guide for Grail integration (sandboxed .pym scripts).
- About the external Grail library, not Remora-specific, but relevant for Remora users.
- Well-written reference doc.

#### HOW_TO_USE_STRUCTURED_AGENTS.md — **KEEP**
- Guide for structured-agents integration.
- External library doc but relevant for Remora users.
- Well-written reference doc.

#### STRUCTURED_AGENTS-HOW_TO_USE_QWEN_MODEL.md — **KEEP, consider MOVE**
- Qwen3 model-specific guide for structured-agents.
- Useful but very specific. Could move to a guides/ subfolder or stay.

#### CONCEPT.md — **DELETE or MERGE**
- Old concept doc that describes V1 architecture: "local orchestration layer", "KernelRunner",
  "Hub Context", "Decision Packet", bundle-based operations.
- Completely superseded by EventBased_Concept.md. References old architecture.
- Should be DELETED — it describes the wrong architecture.

---

## docs/guides/ (5 files)

#### getting-started.md — **KEEP, REVISE**
- Installation, project setup, starting LLM backend, first run, Neovim integration.
- References `pip install remora` — verify. References devenv setup — good.
- Well-structured onboarding guide.

#### customization.md — **KEEP, REVISE**
- Grail tool scripts, bundle config, tree-sitter queries, agent extensions.
- References `.remora/models/*.py` for extensions, `agents/<bundle>/` for tools.
- Good structure, needs accuracy verification.

#### llm-configuration.md — **KEEP, REVISE**
- vLLM setup, external APIs, config reference, model resolution, per-bundle overrides.
- Very comprehensive. Needs verification against current SwarmExecutor code.

#### notetaking-workflow.md — **KEEP, REVISE**
- Markdown notes as agents: sections, todos, frontmatter.
- Well-written workflow guide. Needs verification of node types.

#### programming-workflow.md — **KEEP, REVISE**
- Editor experience: diagnostics, code actions, agent panel, reactive cascade.
- Well-written workflow guide. Needs verification of keybindings and features.

---

## docs/plans/ (11 files)

All plan files are historical implementation plans. Some are referenced by REPO_RULES.md as key docs.

#### EVENT_ARCHITECTURE_ALIGNMENT.md — **KEEP** (referenced by REPO_RULES.md)
- Design doc for EventLog-first architecture. Still authoritative.

#### 2026-03-02-agentnode-design.md — **KEEP** (referenced by REPO_RULES.md)
- AgentNode design spec. Still authoritative.

#### 2026-03-02-agentnode-implementation.md — **KEEP** (referenced by REPO_RULES.md)
- AgentNode implementation plan. Historical but useful reference.

#### 2026-03-01-architectural-unification.md — **KEEP**
- EventLog-first unification plan. Foundation for current architecture.

#### 2026-03-01-graph-viewer-v2-design.md — **MOVE to .hidden/**
- Graph viewer implementation plan. Specific implementation guide.

#### 2026-03-01-zoom-to-cursor.md — **MOVE to .hidden/**
- Zoom-to-cursor feature plan. Specific implementation guide.

#### 2026-03-01-web-graph-view-design.md — **MOVE to .hidden/**
- Web graph view design. Specific implementation guide.

#### 2026-03-01-panel-redesign-impl.md — **MOVE to .hidden/**
- Panel redesign implementation. Specific implementation guide.

#### 2026-03-01-panel-redesign.md — **MOVE to .hidden/**
- Panel redesign concept. Specific implementation guide.

#### 2026-02-26-*.md (3 files) — **MOVE to .hidden/**
- v0.4.0/v0.4.1 refactor plans, contract touchpoints. Pre-EventBased architecture.

#### 2026-02-27-ground-up-analysis.md — **MOVE to .hidden/**
- Ground-up refactor analysis. Pre-EventBased architecture.

---

## docs/reports/ (1 file)

#### cairn_test_coverage.md — **DELETE or REVISE**
- Placeholder with no actual data. Just says "Date: TBD" and shows the command to run.

---

## docs/training_examples/ (6 files)

#### remora/llm_conversations_*.md (4 files) — **MOVE to .hidden/ or DELETE**
- Old LLM conversation logs from FunctionGemma testing (2026-02-20).
- Historical data, not documentation. Not useful for contributors.

#### shell/train_readable.md — **MOVE to .hidden/ or DELETE**
- Training data in readable format. Not documentation.

#### smart_home/train_readable.md — **MOVE to .hidden/ or DELETE**
- Training data in readable format. Not documentation.

---

## Summary Statistics

| Verdict | Count | Notes |
|---------|-------|-------|
| KEEP | 7 | EventBased_Concept, architecture.md, overview.md, LLM_REFERENCE, HOW_TO guides (Grail, SA) |
| KEEP + REVISE | 10 | API_REFERENCE, CONFIGURATION, INSTALLATION, TESTING_GUIDELINES, TROUBLESHOOTING, REMORA_UI_API, guides/*, HOW_TO_CREATE |
| MERGE/CONSOLIDATE | 3 | ARCHITECTURE.md→architecture.md, SPEC.md→other docs, CONCEPT.md→delete |
| MOVE to .hidden/ | 14 | Old plans (7), training examples (6), graph/panel/zoom plans |
| DELETE | 2 | CONCEPT.md (stale), cairn_test_coverage.md (empty placeholder) |

### Key docs/ Issues
1. **Duplicate architecture docs**: ARCHITECTURE.md and architecture.md — consolidate
2. **Stale CONCEPT.md**: Describes V1 architecture, completely wrong for current codebase
3. **plans/ sprawl**: 11 plan files, only 4 are still referenced. Rest should move to .hidden/
4. **training_examples/**: Not documentation at all. Should move out of docs/
5. **Empty report**: cairn_test_coverage.md has no data
