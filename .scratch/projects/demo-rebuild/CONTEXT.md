# CONTEXT — Demo Rebuild

## Current State
Project directory created. Planning complete. About to start execution.

## What Just Happened
- Created project directory with standard files (PLAN, PROGRESS, ASSUMPTIONS, DECISIONS, ISSUES)
- Verified Option A migration is complete (ASTAgentNode removed, AgentRunner exists)
- Confirmed existing remora_demo/ structure needs archiving
- Updated CRITICAL_RULES.md with compaction auto-continue instruction

## What's Next
1. Archive existing remora_demo/ to remora_demo.old/
2. Create new directory structure
3. Start with T1: Create configlib demo project files
4. Then T2: Extension configs + remora.yaml
5. Then T14: MockLLMClient

## Key Decisions
- Two subdirectories: neovim/ (Python 3.13) + web/ (Python 3.14)
- Shared project/ directory for configlib
- T3-T13 skipped (already done via Option A)

## Key Files
- `EVENT_BASED_DEMO_PLAN.md` — Section 2 has exact configlib source code
- `EVENT_BASED_DEMO_PLAN.md` — Section 4 has MockLLM design
- `docs/EventBased_Concept.md` — Authoritative architecture
