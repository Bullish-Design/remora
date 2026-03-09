# Bootstrap SME Node Agent — Plan

## ABSOLUTE EXECUTION RULE
Do all work directly in this session. **Do not use subagents (Task tool).**

## Milestones

1. Define SME schema/tool contract
   - Add/update bootstrap schema/tool assets for node summary generation and Q&A.
   - Define output markdown shape for sidebar rendering.

2. Trigger model for "all nodes on file open"
   - Add event flow to emit per-node activation when a file is opened/focused.
   - Ensure fan-out is deterministic and safe for existing projects.

3. Summary generation + persistence
   - Execute SME turns per node and persist summary markdown in workspace.
   - Verify idempotent refresh behavior.

4. Sidebar integration
   - Render summary markdown for focused node.
   - Add UI control surface for user question prompt.

5. `user_question` tool + correction capture
   - Implement user-question request/response flow.
   - Persist corrections as agent notes for future responses.

6. Verification
   - Unit tests for schema/tool/runtime behavior.
   - Integration tests for file-open fan-out + sidebar summary visibility.

## Acceptance criteria
- Opening a Python file triggers summary generation for all contained nodes.
- Focusing any node shows generated summary markdown in sidebar.
- User can ask question from sidebar flow and receive an answer.
- User correction is persisted and influences subsequent responses.

## ABSOLUTE EXECUTION RULE (REPEATED)
Do all work directly in this session. **Do not use subagents (Task tool).**
