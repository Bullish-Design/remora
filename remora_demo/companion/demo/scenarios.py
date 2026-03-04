"""Demo scenarios — scripted cursor movements and expected outputs.

Each scenario is a sequence of steps that simulate a user working
in the editor. The harness plays these steps, driving the real
CompanionRuntime, and rendering the results.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DemoStep:
    """A single step in a demo scenario.

    Each step moves the cursor, waits for the agent cascade,
    and optionally adds a narration caption.
    """

    file: str
    line: int
    col: int = 0
    caption: str = ""
    pause_seconds: float = 3.0  # How long to display this step
    language: str = ""  # Auto-detect if empty


@dataclass
class DemoScenario:
    """A complete demo scenario with metadata and steps."""

    name: str
    description: str
    workspace_path: str  # Directory to index
    steps: list[DemoStep] = field(default_factory=list)
    pre_narration: str = ""  # Shown before scenario starts
    post_narration: str = ""  # Shown after scenario ends


def coding_scenario(examples_dir: Path) -> DemoScenario:
    """Scenario 1: Developer exploring an unfamiliar codebase.

    The user opens processor.py, moves through the class,
    then jumps to the test file. The sidebar shows related content,
    connections to tests and docs, and structure info.
    """
    src = examples_dir / "src"
    tests = examples_dir / "tests"

    return DemoScenario(
        name="Exploring a Codebase",
        description="A developer opens an unfamiliar project and browses the code. "
        "Companion surfaces related content, tests, and documentation automatically.",
        workspace_path=str(examples_dir),
        pre_narration="Scenario: You've just cloned a project and want to understand the data processing pipeline.",
        post_narration="Companion found the test file, related docs, and similar patterns — all without asking.",
        steps=[
            DemoStep(
                file=str(src / "processor.py"),
                line=1,
                caption="Opening the main processor module...",
                pause_seconds=2.5,
            ),
            DemoStep(
                file=str(src / "processor.py"),
                line=21,
                caption="Looking at the DataProcessor class",
                pause_seconds=3.5,
            ),
            DemoStep(
                file=str(src / "processor.py"),
                line=46,
                caption="Reading the load_data method — what does it do?",
                pause_seconds=4.0,
            ),
            DemoStep(
                file=str(src / "processor.py"),
                line=107,
                caption="The main entry point: process_batch()",
                pause_seconds=4.0,
            ),
            DemoStep(
                file=str(src / "validators.py"),
                line=16,
                caption="Jumping to validators — how are these used?",
                pause_seconds=3.5,
            ),
            DemoStep(
                file=str(tests / "test_processor.py"),
                line=57,
                caption="Now checking the tests for process_batch",
                pause_seconds=4.0,
            ),
        ],
    )


def research_scenario(examples_dir: Path) -> DemoScenario:
    """Scenario 2: Researcher writing about technical concepts.

    The user is reading and writing markdown documents about CQRS
    and the architecture. The sidebar surfaces related code, definitions,
    and connections between notes.
    """
    docs = examples_dir / "docs"
    src = examples_dir / "src"

    return DemoScenario(
        name="Document Research",
        description="A researcher is reading technical documentation and notes. "
        "Companion surfaces related code, other notes, and concept connections.",
        workspace_path=str(examples_dir),
        pre_narration="Scenario: You're studying the architecture docs to write a technical review.",
        post_narration="Companion connected the docs to actual code and surfaced related notes automatically.",
        steps=[
            DemoStep(
                file=str(docs / "architecture.md"),
                line=1,
                caption="Opening the architecture documentation...",
                pause_seconds=2.5,
                language="markdown",
            ),
            DemoStep(
                file=str(docs / "architecture.md"),
                line=16,
                caption="Reading about the DataProcessor component",
                pause_seconds=4.0,
                language="markdown",
            ),
            DemoStep(
                file=str(docs / "architecture.md"),
                line=39,
                caption="The CQRS pattern section — what is this?",
                pause_seconds=4.0,
                language="markdown",
            ),
            DemoStep(
                file=str(docs / "cqrs_notes.md"),
                line=1,
                caption="Jumping to the CQRS notes for more detail",
                pause_seconds=3.5,
                language="markdown",
            ),
            DemoStep(
                file=str(docs / "cqrs_notes.md"),
                line=34,
                caption="How is CQRS implemented in this project?",
                pause_seconds=4.0,
                language="markdown",
            ),
            DemoStep(
                file=str(src / "processor.py"),
                line=46,
                caption="Following the link to the actual implementation",
                pause_seconds=4.0,
            ),
        ],
    )


def get_all_scenarios(examples_dir: Path) -> list[DemoScenario]:
    """Get all available demo scenarios."""
    return [
        coding_scenario(examples_dir),
        research_scenario(examples_dir),
    ]
