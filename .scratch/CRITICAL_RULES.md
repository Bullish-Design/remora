# CRITICAL RULES — READ EVERY SESSION

## NO SUBAGENTS — ABSOLUTE RULE
- NEVER use the Task tool
- NEVER dispatch parallel agents
- NEVER use @mention subagents
- ALL work happens in this single agent context
- This is NON-NEGOTIABLE. The user was emphatic about this.

## Other Rules
- Write to `.scratch/` frequently to preserve context across compaction
- TDD when implementing code
- DRY/YAGNI
- No isinstance checks in codebase (except projection dispatch which is internal)
- AgentNode is a single Pydantic BaseModel, no subclasses

## Implementation Plan Status
Plan written: `docs/plans/2026-03-02-agentnode-implementation.md`
- Phase 1 (Tasks 1-11): Create AgentNode, extensions, events, projection, wire into EventStore
- Phase 2 (Tasks 12-17): Migrate consumers (reconciler, runner, executor, LSP, remove old files)
- All tasks have exact code, test commands, and commit messages
- NO tasks started yet — plan is ready for execution

## Key Files
- Design spec: `docs/plans/2026-03-02-agentnode-design.md`
- Implementation plan: `docs/plans/2026-03-02-agentnode-implementation.md`
- Vision doc: `docs/EventBased_Concept.md`
- Architecture alignment: `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md`
