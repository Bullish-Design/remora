# Bootstrap SME Node Agent — Decisions

## D1: Project scope starts in root bootstrap assets
**Decision**: Begin this feature by extending root `bootstrap/` schemas/tools and runtime wiring, then integrate with companion sidebar behavior.

**Rationale**: Matches user request and existing bootstrap architecture.

## D2: SME contract is represented by `subject_matter_expert.yaml`
**Decision**: Add `bootstrap/agents/subject_matter_expert.yaml` as the first-class SME schema contract.

**Rationale**:
- Keeps the contract in the same system-agent catalog as current bootstrap schemas.
- Lets workspace schemas extend this profile for Python node guidance.
- Encodes required summary markdown sections ("What I am", "What I do", "How I do it") directly in the system prompt.

## D3: `user_question` tool emits `HumanInputRequestEvent` via `event_write`
**Decision**: Add `bootstrap/tools/user_question.pym` with inputs `question`, `request_id`, and `node_id`, and route it through the existing `event_write` bedrock external.

**Rationale**:
- Reuses existing bootstrap tool external surface (no new bedrock function required).
- Preserves compatibility with current tool compilation/dispatch path.
- Establishes a concrete event payload contract for later UI/runtime input handling.

## D4: File-open activation is keyed by unassigned code nodes, not just module/file nodes
**Decision**: Introduce `find_unassigned_nodes(..., file_path=...)` and use it for file-open fan-out.

**Rationale**:
- Matches user goal: activate all nodes in an opened file.
- Keeps module-only assignment behavior available via the existing module wrapper path.
- Reuses existing assignment model (`agent` graph nodes with `assigned_node_id`) without schema changes.

## D5: Fan-out execution runs in parallel per file open, scheduled off the did_open path
**Decision**: Add `BootstrapRunner.run_for_file(file_path)` with parallel `handle_agent_needed` calls and trigger it from LSP `did_open` via background task.

**Rationale**:
- Satisfies “all at once” activation intent without blocking document open.
- Uses existing bootstrap runner/service instances and DB paths.
- Maintains deterministic candidate selection order while allowing concurrent activation.

## D6: New node agents are pre-seeded into SME mode on first activation
**Decision**: In `handle_agent_needed`, if `schema.yaml` is missing, seed it to extend `subject_matter_expert`; if `summary.md` is missing, seed a markdown template.

**Rationale**:
- Avoids initial fallback to generic bootstrap-default behavior for new node agents.
- Gives immediate deterministic summary structure per node.
- Uses existing Cairn workspace writes (no new storage mechanism).

## D7: Sidebar summary rendering uses existing workspace panel mechanism
**Decision**: Add `summary.md` as a new panel in companion `build_workspace_panels()` instead of adding a bespoke sidebar section.

**Rationale**:
- Reuses current workspace-driven sidebar architecture.
- Keeps UI behavior consistent with other workspace files.
- Minimizes scope while making SME output visible at node focus time.

## D8: Human-response routing is explicit through `request_id` submit payloads
**Decision**: Extend `$/remora/submitInput` handling to support `request_id` responses (`request_id`, `agent_id`, `node_id`, `question`, `input`) and route them to bootstrap runner.

**Rationale**:
- Avoids ambiguous inference when multiple user-question requests exist.
- Keeps chat and proposal flows unchanged while adding a distinct response path.
- Provides enough context for deterministic bootstrap re-activation.

## D9: Bootstrap user-question prompts are bridged to Neovim via `$/remora/requestInput`
**Decision**: Subscribe to bootstrap `BootstrapEvent` on LSP startup and forward `HumanInputRequestEvent(kind=user_question)` to existing `$/remora/requestInput` UX.

**Rationale**:
- Reuses existing Neovim input prompt flow.
- Delivers immediate prompt behavior instead of waiting for passive panel refresh.
- Keeps transport compatibility without adding new protocol methods.

## D10: Corrections are persisted eagerly before model turn execution
**Decision**: On `HumanInputResponseEvent`, append correction entries into `notes.md` and `summary.md` (`## User corrections`) before running the SME turn.

**Rationale**:
- Guarantees correction capture even if model output is empty or fails.
- Gives the model durable correction context for the same activation.
- Meets user requirement that corrected guidance is retained.

## D11: Validate Neovim bridge path with automated startup/notification tests before interactive QA
**Decision**: Add unit-level regression tests for the startup bridge subscription and request-id fallback routing, then use a headless Neovim plugin load smoke test as a prerequisite before manual interactive verification.

**Rationale**:
- Catches protocol regressions quickly without requiring a full editor session for every iteration.
- Confirms both critical routing paths (`BootstrapEvent -> $/remora/requestInput` and `$/remora/submitInput` fallback).
- Reduces risk before final manual UX confirmation in a real Neovim environment.
