"""Comprehensive parser tests — covers BUG-2 regression and edge cases."""

import pytest

from structured_agents.models.parsers import QwenResponseParser


class TestQwenResponseParser:
    def setup_method(self):
        self.parser = QwenResponseParser()

    def test_parse_api_tool_calls_preserves_id(self):
        """BUG-2 regression: API-provided tool call IDs must be preserved."""
        tool_calls = [
            {
                "id": "call_original_123",
                "type": "function",
                "function": {"name": "add", "arguments": '{"x": 1, "y": 2}'},
            }
        ]
        content, parsed = self.parser.parse(None, tool_calls)
        assert content is None
        assert len(parsed) == 1
        assert parsed[0].id == "call_original_123"
        assert parsed[0].name == "add"
        assert parsed[0].arguments == {"x": 1, "y": 2}

    def test_parse_api_tool_calls_malformed_json(self):
        """Malformed arguments JSON should default to empty dict."""
        tool_calls = [
            {
                "id": "call_bad",
                "type": "function",
                "function": {"name": "bad_tool", "arguments": "not json{"},
            }
        ]
        content, parsed = self.parser.parse(None, tool_calls)
        assert len(parsed) == 1
        assert parsed[0].arguments == {}

    def test_parse_xml_tool_calls(self):
        """XML-embedded tool calls should be parsed correctly."""
        content = '<tool_call>{"name": "add", "arguments": {"x": 1}}</tool_call>'
        result_content, parsed = self.parser.parse(content, None)
        assert result_content is None
        assert len(parsed) == 1
        assert parsed[0].name == "add"

    def test_parse_plain_text(self):
        """Plain text without tool calls returns content and empty list."""
        content, parsed = self.parser.parse("Just a response", None)
        assert content == "Just a response"
        assert parsed == []

    def test_parse_none_content_no_tools(self):
        """None content and no tools returns None and empty list."""
        content, parsed = self.parser.parse(None, None)
        assert content is None
        assert parsed == []

    def test_parse_multiple_api_tool_calls(self):
        """Multiple tool calls should all be parsed with correct IDs."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "a", "arguments": "{}"},
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {"name": "b", "arguments": '{"x": 1}'},
            },
        ]
        _, parsed = self.parser.parse(None, tool_calls)
        assert len(parsed) == 2
        assert parsed[0].id == "call_1"
        assert parsed[1].id == "call_2"

    def test_parse_empty_arguments(self):
        """Empty arguments should be handled."""
        tool_calls = [
            {
                "id": "call_empty",
                "type": "function",
                "function": {"name": "no_args", "arguments": "{}"},
            }
        ]
        content, parsed = self.parser.parse(None, tool_calls)
        assert len(parsed) == 1
        assert parsed[0].arguments == {}
