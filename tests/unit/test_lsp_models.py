# tests/unit/test_lsp_models.py
from __future__ import annotations

from remora.lsp.models import (
    ASTAgentNode,
    HumanChatEvent,
    ToolSchema,
    RewriteProposal,
)


def _make_node(**overrides):
    data = {
        "remora_id": "rm_test123",
        "node_type": "function",
        "name": "test_node",
        "file_path": "file:///test.py",
        "start_line": 1,
        "end_line": 5,
        "source_code": "def foo(): pass",
        "source_hash": "hash",
    }
    data.update(overrides)
    return ASTAgentNode(**data)


def _make_proposal():
    return RewriteProposal(
        proposal_id="rm_prop1234",
        agent_id="rm_test1234",
        file_path="file:///test.py",
        old_source="def foo(): return 1",
        new_source="def foo(): return 2",
        start_line=1,
        end_line=1,
        correlation_id="corr_1",
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


def test_ast_agent_node_to_code_lens():
    node = _make_node()
    lens = node.to_code_lens()
    assert lens.command.command == "remora.selectAgent"
    assert node.remora_id in lens.command.title


def test_ast_agent_node_to_hover():
    node = _make_node()
    hover = node.to_hover()
    assert node.remora_id in hover.contents.value


def test_ast_agent_node_to_code_actions():
    node = _make_node()
    actions = node.to_code_actions()
    commands = {action.command.command for action in actions if action.command}
    assert "remora.chat" in commands
    assert "remora.requestRewrite" in commands
    assert "remora.messageNode" in commands


def test_rewrite_proposal_to_code_actions():
    proposal = _make_proposal()
    actions = proposal.to_code_actions()
    commands = {action.command.command for action in actions}
    assert "remora.acceptProposal" in commands
    assert "remora.rejectProposal" in commands


def test_event_defaults():
    evt = HumanChatEvent(to_agent="rm_test", message="hi", correlation_id="c1", timestamp=0.1)
    assert evt.event_type == "HumanChatEvent"
    assert "rm_test" in evt.summary
