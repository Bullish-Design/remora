"""Tests for summarizers."""

from remora.context.summarizers import (
    LinterSummarizer,
    TestRunnerSummarizer,
    ToolSidePassthrough,
)


class TestLinterSummarizer:
    def test_summarize_no_errors(self):
        summarizer = LinterSummarizer()
        result = summarizer.summarize({"errors": []})
        assert "No lint errors" in result

    def test_summarize_with_errors(self):
        summarizer = LinterSummarizer()
        result = summarizer.summarize({"errors": [1, 2, 3]})
        assert "3 lint errors" in result

    def test_summarize_with_fixes(self):
        summarizer = LinterSummarizer()
        result = summarizer.summarize({"errors": [1], "fixed": 2})
        assert "Fixed 2" in result
        assert "1 remaining" in result

    def test_extract_knowledge(self):
        summarizer = LinterSummarizer()
        knowledge = summarizer.extract_knowledge({"errors": [1, 2], "fixed": 1})
        assert knowledge["lint_errors_remaining"] == 2
        assert knowledge["lint_errors_fixed"] == 1


class TestTestRunnerSummarizer:
    def test_summarize_all_passed(self):
        summarizer = TestRunnerSummarizer()
        result = summarizer.summarize({"passed": 5, "failed": 0})
        assert "All 5 tests passed" in result

    def test_summarize_with_failures(self):
        summarizer = TestRunnerSummarizer()
        result = summarizer.summarize({"passed": 3, "failed": 2})
        assert "2 of 5 tests failed" in result


class TestToolSidePassthrough:
    def test_passes_through_summary(self):
        summarizer = ToolSidePassthrough()
        result = summarizer.summarize({"summary": "Custom summary"})
        assert result == "Custom summary"

    def test_falls_back_to_message(self):
        summarizer = ToolSidePassthrough()
        result = summarizer.summarize({"message": "Operation complete"})
        assert result == "Operation complete"

    def test_generic_fallback(self):
        summarizer = ToolSidePassthrough()
        result = summarizer.summarize({"data": "something"})
        assert result == "Tool completed"
