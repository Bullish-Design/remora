"""Summarizer framework for tool result distillation.

Summarizers convert raw tool outputs into concise summaries for
the Decision Packet. They are the fallback when tools don't provide
their own summaries.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Summarizer(ABC):
    """Base class for tool result summarizers.

    Implement this to create custom summarizers for specific tools.
    Register them with ContextManager.register_summarizer().
    """

    @abstractmethod
    def summarize(self, raw_result: Any) -> str:
        """Generate a summary from raw tool output."""
        raise NotImplementedError

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        """Extract knowledge entries from raw output."""
        return {}


class ToolSidePassthrough(Summarizer):
    """Passes through tool-provided summaries."""

    def summarize(self, raw_result: Any) -> str:
        if isinstance(raw_result, dict):
            if "summary" in raw_result:
                return str(raw_result["summary"])
            if "message" in raw_result:
                return str(raw_result["message"])
        return "Tool completed"

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result.get("knowledge_delta", {})
        return {}


class LinterSummarizer(Summarizer):
    """Summarizer for linter tool results."""

    def summarize(self, raw_result: Any) -> str:
        if not isinstance(raw_result, dict):
            return "Ran linter"

        errors = raw_result.get("errors", [])
        fixed = raw_result.get("fixed", 0)

        if fixed > 0:
            remaining = len(errors)
            if remaining == 0:
                return f"Fixed all {fixed} lint errors"
            return f"Fixed {fixed} lint errors, {remaining} remaining"

        if not errors:
            return "No lint errors found"

        return f"Found {len(errors)} lint errors"

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        if not isinstance(raw_result, dict):
            return {}

        return {
            "lint_errors_remaining": len(raw_result.get("errors", [])),
            "lint_errors_fixed": raw_result.get("fixed", 0),
        }


class TestRunnerSummarizer(Summarizer):
    """Summarizer for test runner results."""

    def summarize(self, raw_result: Any) -> str:
        if not isinstance(raw_result, dict):
            return "Ran tests"

        passed = raw_result.get("passed", 0)
        failed = raw_result.get("failed", 0)
        total = passed + failed

        if failed == 0:
            return f"All {total} tests passed"

        return f"{failed} of {total} tests failed"

    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        if not isinstance(raw_result, dict):
            return {}

        return {
            "tests_passed": raw_result.get("passed", 0),
            "tests_failed": raw_result.get("failed", 0),
        }


BUILTIN_SUMMARIZERS: dict[str, Summarizer] = {
    "run_linter": LinterSummarizer(),
    "apply_fix": LinterSummarizer(),
    "run_tests": TestRunnerSummarizer(),
}


def get_default_summarizers() -> dict[str, Summarizer]:
    """Get a copy of built-in summarizers."""
    return BUILTIN_SUMMARIZERS.copy()
