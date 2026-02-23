"""LLM-based summarizer for AST Summary demo."""

from __future__ import annotations

from pathlib import Path

from openai import AsyncOpenAI

from demo.config import DemoConfig
from demo.events import emit_event
from demo.models import AstNode

SYSTEM_PROMPTS = {
    ".py": """You are an expert code summarizer. Given a Python code block, provide a concise 1-2 sentence summary of what it does.

Focus on:
- What the code does (not how)
- Key inputs/outputs if obvious
- Purpose within the larger codebase

Respond ONLY with the summary, no explanations.""",
    ".toml": """You are an expert configuration file summarizer. Given a TOML configuration block, provide a concise 1-2 sentence summary of what it configures.

Focus on:
- What this configuration controls
- Key settings and their purposes
- Project/package metadata if present

Respond ONLY with the summary, no explanations.""",
    ".md": """You are an expert documentation summarizer. Given a Markdown document block, provide a concise 1-2 sentence summary of its contents.

Focus on:
- What topic this covers
- Key sections if obvious
- Purpose of the document

Respond ONLY with the summary, no explanations.""",
}

ROLLUP_PROMPT = """You are an expert code analyst. Given a code element and summaries of its child elements, provide a concise 1-2 sentence summary that describes what this element does and how its children contribute.

Code element type: {node_type}
Code element name: {node_name}

Child summaries:
{child_summaries}

Provide a rollup summary that describes this element's purpose and how its children contribute. Respond ONLY with the summary, no explanations."""


def _get_prompt_for_node(node: AstNode, child_summaries: list[str]) -> tuple[str, list[dict[str, str]]]:
    """Get the prompt and messages for a node based on its type."""
    ext = Path(node.source_text.split("\n")[0] if "\n" in node.source_text else "").suffix or ".py"

    if child_summaries:
        prompt = ROLLUP_PROMPT.format(
            node_type=node.node_type,
            node_name=node.name,
            child_summaries="\n".join(f"- {s}" for s in child_summaries),
        )
        system = "You are an expert code analyst."
    else:
        prompt = node.source_text[:3000]
        system = SYSTEM_PROMPTS.get(ext, SYSTEM_PROMPTS[".py"])

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    return prompt, messages


class Summarizer:
    """LLM-based summarizer using vLLM server."""

    def __init__(self, config: DemoConfig | None = None) -> None:
        self.config = config or DemoConfig()
        self.client = AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

    async def summarize(self, node: AstNode, child_summaries: list[str]) -> str:
        """Generate a summary for a node using the LLM."""
        _, messages = _get_prompt_for_node(node, child_summaries)

        emit_event("llm_request", node.name, node.node_type, "Sending request to vLLM")

        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.3,
                max_tokens=256,
            )

            summary = response.choices[0].message.content
            if not summary:
                summary = "(No summary generated)"

            emit_event(
                "llm_response",
                node.name,
                node.node_type,
                f"Received response ({len(summary)} chars)",
            )

            return summary.strip()

        except Exception as e:
            error_msg = str(e)
            emit_event("llm_error", node.name, node.node_type, f"LLM error: {error_msg[:50]}")
            return f"[Error: {error_msg[:100]}]"


async def generate_summary(
    node: AstNode,
    child_summaries: list[str],
    summarizer: Summarizer | None = None,
) -> str:
    """Generate a summary for a node using the LLM summarizer."""
    if summarizer is None:
        summarizer = Summarizer()

    return await summarizer.summarize(node, child_summaries)
