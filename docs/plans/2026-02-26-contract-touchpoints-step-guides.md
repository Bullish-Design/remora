# Contract Touchpoints + Done Criteria Blocks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Contract Touchpoints and Done Criteria sections to Step 01–08 refactor guides, using a consistent template and required callouts.

**Architecture:** Treat each step guide as a markdown spec. Insert the template blocks immediately after the Overview section and before the first step/implementation section so readers see contracts and completion checks early. Keep language aligned to the core contracts in `V040_GROUND_UP_REFACTOR_PLAN.md`.

**Tech Stack:** Markdown documentation in `.refactor/`.

---

### Task 1: Add template blocks to Steps 01–04

**Files:**
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_01.md`
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_02.md`
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_03.md`
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_04.md`

**Step 1: Insert Contract Touchpoints section after Overview**

Use this template (fill in the step-specific bullets):

```markdown
## Contract Touchpoints
- **Core contracts:** <list the core contracts this step touches>
- **Key integrations:** <call out key protocol/behavior that must remain aligned>
- **Data flow hooks:** <note event/data exchange expectations>
```

Ensure Step 01 explicitly calls out the Observer protocol expectations in the EventBus.
Ensure Step 02 explicitly calls out Grail `files` dict population expectations.

**Step 2: Insert Done Criteria section after Contract Touchpoints**

Use this template:

```markdown
## Done Criteria
- [ ] <verification item 1>
- [ ] <verification item 2>
- [ ] <verification item 3>
```

**Step 3: Keep existing content intact below the new blocks**

Do not rearrange the rest of the guide; only insert the two sections.

---

### Task 2: Add template blocks to Steps 05–08

**Files:**
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_05.md`
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_06.md`
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_07.md`
- Modify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_08.md`

**Step 1: Insert Contract Touchpoints section after Overview**

Reuse the same Contract Touchpoints template from Task 1. Ensure Step 05 explicitly calls out the `Agent.from_bundle()` environment override requirement described in `V040_GROUND_UP_REFACTOR_PLAN.md`.

**Step 2: Insert Done Criteria section after Contract Touchpoints**

Reuse the Done Criteria template from Task 1 with step-specific checks.

**Step 3: Keep existing content intact below the new blocks**

---

### Task 3: Validate content and wording

**Files:**
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_01.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_02.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_03.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_04.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_05.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_06.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_07.md`
- Verify: `.worktrees/v040-refactor-plan/.refactor/GROUND_UP_REFACTOR_GUIDE-STEP_08.md`

**Step 1: Confirm section placement**

Check each file to ensure the two new sections appear after Overview and before the first step/implementation heading.

**Step 2: Confirm required mentions**

Verify Step 01 mentions Observer protocol alignment, Step 02 mentions Grail `files` dict population, and Step 05 mentions the `Agent.from_bundle()` environment override requirement.

**Step 3: No tests required**

These are documentation-only edits; no test runs are needed.
