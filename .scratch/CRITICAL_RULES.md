# CRITICAL RULES — READ EVERY SESSION

This is the entrypoint for any agent working in this codebase.
Read this file FIRST after every compaction or session start.

---

## 1. Session Startup

1. Read this file in full.
2. Identify which project you are working on.
3. Read that project's `CONTEXT.md` to resume where you left off.
4. Check `PROGRESS.md` for current task status.
5. Check `ISSUES.md` for known roadblocks before starting work.

---

## 2. Project Convention

Every task, feature, or refactor gets its own project directory:

```
.scratch/projects/<project-name>/
```

Use kebab-case for directory names (e.g. `option-a-unification`, `web-demo-migration`).

### Standard Files

Each project directory contains these standard files:

| File | Purpose |
|------|---------|
| `PROGRESS.md` | Task tracker with status (pending/in-progress/done). The source of truth for what's been completed and what remains. |
| `CONTEXT.md` | Current state for resumption after compaction. What just happened, what's next, key variable state. Update this before any large context shift. |
| `PLAN.md` | Implementation plan. Ordered steps, dependencies, acceptance criteria. |
| `DECISIONS.md` | Key decisions with rationale. Load `ASSUMPTIONS.md` before adding entries here. |
| `ASSUMPTIONS.md` | Context loaded before making decisions. Project audience, user scenarios, constraints, invariants — anything that shapes *why* a decision gets made. |
| `ISSUES.md` | Roadblock index. After 3 failed attempts at the same problem, stop and create an `ISSUE_<num>.md` in the project directory with a detailed log of what was tried, what failed, and why. Reference it from `ISSUES.md`. |

### Project-Scoped Scratch Notes

ALL scratch notes, working files, ad-hoc explorations, and temporary analysis for a project go inside that project's directory — never loose in `.scratch/`. Name them descriptively (e.g. `watcher-refactor-notes.md`, `db-schema-analysis.md`). The standard files above are the convention; additional files are encouraged whenever they help preserve context.

### Project Lifecycle

- **Starting**: Create the directory and at minimum `PLAN.md` and `ASSUMPTIONS.md`.
- **Working**: Keep `PROGRESS.md` and `CONTEXT.md` current as you go.
- **Blocked**: Document in `ISSUES.md` with a linked `ISSUE_<num>.md`.
- **Complete**: Mark all tasks done in `PROGRESS.md`. Update `CONTEXT.md` with a final summary.

---

## 3. Context Preservation

- Write to `.scratch/projects/<project>/` frequently to preserve context across compaction.
- Update `CONTEXT.md` whenever you finish a significant chunk of work or are about to shift focus.
- `CONTEXT.md` should always answer: *"If I lost all memory right now, what do I need to know to continue?"*
- When reasoning through a non-obvious decision, write it to `DECISIONS.md` with the rationale and which assumptions informed it.

---

## 4. Coding Standards

- **TDD**: Write a failing test first, implement, verify the test passes.
- **DRY/YAGNI**: No duplication. No speculative features.
- **No isinstance in business logic**: Projection dispatch (internal) is the exception.
- **AgentNode**: Single Pydantic BaseModel. No subclasses anywhere.

---

## 5. Large Documents

When writing large documents:

1. Write a detailed table of contents (with brief description per section) and SAVE IT TO FILE first.
2. Go section by section, APPENDING to the file as you go.
3. This prevents context window overflow from trying to write the whole thing at once.

---

## 6. Key Reference Files

| Document | Path |
|----------|------|
| Vision / architecture | `docs/EventBased_Concept.md` |
| Architecture alignment | `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md` |
| AgentNode design spec | `docs/plans/2026-03-02-agentnode-design.md` |
| AgentNode impl plan | `docs/plans/2026-03-02-agentnode-implementation.md` |
