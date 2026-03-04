"""Extension config for scaffold nodes: self-initializing stubs.

A scaffold node is created empty (stub) and self-initializes by gathering
context from its parent, siblings, and project structure. This extension
matches any node whose source_code is a stub pattern (empty, pass-only,
ellipsis-only, comment/docstring-only) and provides a system prompt
instructing the agent to fill itself in using ``rewrite_self()``.
"""

import re

from remora.extensions import AgentExtension

# ---------------------------------------------------------------------------
# Stub detection (mirrors _is_stub logic from projections)
# ---------------------------------------------------------------------------

_STUB_INLINE_RE = re.compile(
    r"^\s*(?:(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?\s*:\s*(?:pass|\.\.\.)"
    r"|class\s+\w+(?:\([^)]*\))?\s*:\s*(?:pass|\.\.\.))\s*$",
    re.DOTALL,
)

_STUB_BLOCK_RE = re.compile(
    r"^\s*(?:(?:async\s+)?def\s+\w+\s*\([^)]*\)\s*(?:->[^:]+)?\s*:"
    r"|class\s+\w+(?:\([^)]*\))?\s*:)"
    r"\s*\n"
    r"(?:\s*(?:#[^\n]*|\"\"\"[^\"]*\"\"\"|\'\'\'[^\']*\'\'\')\s*\n)*"
    r"\s*(?:pass|\.\.\.)\s*$",
    re.DOTALL,
)

_TRIVIAL_CONTENT_RE = re.compile(
    r"^(?:\s*(?:#[^\n]*|\"\"\"[^\"]*\"\"\"|\'\'\'[^\']*\'\'\')?\s*\n?)*$",
    re.DOTALL,
)


def _is_stub(source_code: str) -> bool:
    """Return True if source_code is empty, trivial, or a known stub pattern."""
    stripped = source_code.strip()
    if not stripped:
        return True
    if _TRIVIAL_CONTENT_RE.fullmatch(source_code):
        return True
    if _STUB_INLINE_RE.fullmatch(stripped):
        return True
    if _STUB_BLOCK_RE.fullmatch(stripped):
        return True
    return False


class ScaffoldInitializerExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
        # Empty/whitespace-only source is always a stub regardless of file type
        if not source_code.strip():
            return True
        # Python-specific stub patterns only apply to .py files
        if not file_path.endswith(".py"):
            return False
        return _is_stub(source_code)

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "ScaffoldInitializer",
            "custom_system_prompt": (
                "You are a scaffold initializer agent. Your node was created as an "
                "empty stub and needs to be filled in with real implementation. "
                "Examine the scaffold context provided (parent source, sibling nodes, "
                "and intent) to understand what this node should do. Then use "
                "`rewrite_self()` to replace the stub with a complete, working "
                "implementation that fits naturally into the surrounding codebase."
            ),
            "extra_subscriptions": [
                {
                    "event_types": ["ScaffoldRequestEvent"],
                },
            ],
        }
