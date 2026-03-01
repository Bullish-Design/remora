# tests/unit/test_lsp_models.py
from __future__ import annotations

from remora.lsp.models import (
    ASTAgentNode,
    ToolSchema,
    RewriteProposal,
)


def test_tool_schema_to_llm_tool():
    tool = ToolSchema(
        name="my_tool",
        description="Does something",
        parameters={
            "type": "object",
            "properties": {
                "arg1": {"type": "string"},
            },
        },
    )
    llm = tool.to_llm_tool()
    assert llm["function"]["name"] == "my_tool"


def test_rewrite_proposal_diff():
    proposal = RewriteProposal(
        proposal_id="rm_prop1234",
        agent_id="rm_test1234",
        file_path="file:///test.py",
        old_source="def foo(): return 1",
        new_source="def foo(): return 2",
        start_line=1,
        end_line=1,
        correlation_id="corr_1",
    )
    assert proposal.diff
    ws_edit = proposal.to_workspace_edit()
    assert ws_edit.changes
