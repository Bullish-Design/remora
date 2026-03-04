# Plan — Remora Docs

## NO SUBAGENTS — Do all work directly. Never use the Task tool.

## Deliverables

```
docs/
├── overview.md                    # 1. High-Level Overview
├── architecture.md                # 2. Technical/Architectural Overview
├── guides/
│   ├── getting-started.md         # 3. Setup, installation, first run
│   ├── programming-workflow.md    # 4. Using Remora for coding
│   ├── notetaking-workflow.md     # 5. Using Remora for markdown/notes
│   ├── customization.md           # 6. Custom tools, queries, agents
│   └── llm-configuration.md      # 7. vLLM, external APIs, model config
```

## Steps

1. Create project tracking files (PLAN, ASSUMPTIONS, PROGRESS, CONTEXT)
2. Read remaining source files for LLM/model config details:
   - `src/remora/core/kernel_factory.py`
   - `src/remora/core/swarm_executor.py`
   - `src/remora/extensions.py`
   - `docs/HOW_TO_USE_STRUCTURED_AGENTS.md`
   - `docs/STRUCTURED_AGENTS-HOW_TO_USE_QWEN_MODEL.md`
3. Write `docs/overview.md` (TOC first, then sections)
4. Write `docs/architecture.md` (TOC first, then sections)
5. Create `docs/guides/` directory
6. Write `docs/guides/getting-started.md`
7. Write `docs/guides/programming-workflow.md`
8. Write `docs/guides/notetaking-workflow.md`
9. Write `docs/guides/customization.md`
10. Write `docs/guides/llm-configuration.md`
11. Final review, update PROGRESS and CONTEXT

## Large Document Rule
For each doc: write TOC first → save → write section by section → append.

## NO SUBAGENTS — Do all work directly. Never use the Task tool.
