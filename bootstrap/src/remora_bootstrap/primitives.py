"""Bootstrap turn primitives.

These are the core data models for describing agent turns. They are
pure data structures with no execution logic — the runtime resolves them.

Six types, nothing else:

    PromptNode  = str | ToolRef | Concat | InputGate
    Step        = name + PromptNode
    ContextPipeline = ordered Steps
    TurnSchema  = system + context + tools + loop bounds

A TurnSchema describes the shape of one agent turn. The runtime:
  1. Resolves ``system`` into a string (calling any ToolRefs)
  2. Walks the ContextPipeline in order, resolving each Step and making
     its output available as ``"$step_name"`` in later Step args
  3. Concatenates resolved Step outputs into the user message
  4. Runs the LLM loop with the declared grail tools

ToolRef args may reference prior step outputs:
    "$step_name"        -> the full string output of that step
    "$step_name.field"  -> dot-path into the step's parsed JSON output
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


# ---------------------------------------------------------------------------
# PromptNode — the recursive content atom
# ---------------------------------------------------------------------------

PromptNode = Union[str, "ToolRef", "Concat", "InputGate"]
"""One piece of prompt content. Resolves to a string at runtime.

- str       : literal text, no resolution needed
- ToolRef   : call a grail tool, output becomes the content
- Concat    : join a sequence of PromptNodes (empty parts are skipped)
- InputGate : pause and collect human input
"""


@dataclass(slots=True, frozen=True)
class ToolRef:
    """Call a grail tool and use its output as content.

    This covers the "read context before the LLM sees it" use case:
    read the current source, fetch recent history, inspect related nodes, etc.
    These are pre-turn tool calls — the LLM does not see them as tool calls,
    it just sees their resolved output in the prompt.

    Args:
        tool:    grail tool name (pym script name without extension)
        args:    tool arguments. String values may reference prior pipeline
                 step outputs: ``"$step_name"`` or ``"$step_name.field"``
        extract: optional dot-path into the tool's JSON output to extract a
                 specific field. If None, the raw output is stringified.
    """

    tool: str
    args: dict[str, str] = field(default_factory=dict)
    extract: str | None = None


@dataclass(slots=True, frozen=True)
class Concat:
    """Join multiple PromptNodes into one string.

    Parts that resolve to the empty string are omitted. This means
    conditional inclusion is handled at the tool level: a ToolRef that
    returns "" when a condition isn't met is simply skipped.

    Args:
        parts:     sequence of PromptNodes to resolve and join
        separator: string inserted between non-empty parts (default: "")
    """

    parts: tuple[PromptNode, ...]
    separator: str = ""


@dataclass(slots=True, frozen=True)
class InputGate:
    """Pause the context pipeline and collect input from the user.

    Resolves to the user's response. In non-interactive (batch) mode,
    the runtime uses ``default`` if set, otherwise raises ``InputRequired``.

    Args:
        name:    identifier for this gate; its output is referenceable as
                 ``"$name"`` in later pipeline steps
        prompt:  shown to the user before collecting input (a PromptNode,
                 so it can itself contain tool calls)
        default: fallback for non-interactive mode
    """

    name: str
    prompt: PromptNode
    default: str | None = None


# ---------------------------------------------------------------------------
# ContextPipeline — ordered steps that build up context
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Step:
    """One named step in a context pipeline.

    The step's resolved output is stored as ``"$name"`` and is available
    in all subsequent Step args via string interpolation.

    Args:
        name:    unique identifier within the pipeline
        content: the PromptNode to resolve for this step
    """

    name: str
    content: PromptNode


@dataclass(slots=True, frozen=True)
class ContextPipeline:
    """Ordered sequence of Steps that assembles context before the LLM turn.

    Steps run in declaration order. Each step can reference the resolved
    output of any prior step. All step outputs are appended to the user
    message in order (empty outputs are skipped).

    Args:
        steps: ordered tuple of Steps
    """

    steps: tuple[Step, ...]

    @classmethod
    def empty(cls) -> ContextPipeline:
        return cls(steps=())


# ---------------------------------------------------------------------------
# TurnSchema — the root descriptor for one agent turn
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class TurnSchema:
    """Complete description of the shape of one agent turn.

    This is what a bundle.yaml is trying to express, but as a data
    structure instead of a config file. Agents build TurnSchemas using
    grail tools on their cairn workspace, then return them to the runtime.

    Args:
        system:      system prompt content. Resolved once before the LLM
                     loop starts. May include ToolRefs for dynamic context
                     (e.g., read the agent's own role description).
        context:     pipeline that builds the user-visible context.
                     Resolved in full before the first LLM turn.
        tools:       names of grail tools the LLM may call during its turn.
                     These are the interactive tools, not the pre-turn reads.
        max_turns:   maximum LLM loop iterations before forced termination.
        termination: string the LLM outputs to signal it is done.
    """

    system: PromptNode
    context: ContextPipeline = field(default_factory=ContextPipeline.empty)
    tools: tuple[str, ...] = field(default_factory=tuple)
    max_turns: int = 1
    termination: str = "done"


__all__ = [
    "PromptNode",
    "ToolRef",
    "Concat",
    "InputGate",
    "Step",
    "ContextPipeline",
    "TurnSchema",
]
