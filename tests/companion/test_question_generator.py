"""Tests for the question_generator analyzer agent.

The question generator produces contextual questions based on
the user's current context and discovered connections. It writes
Question objects to /companion/analysis/questions/*.
"""

from __future__ import annotations

import pytest

from remora_demo.companion.agents.base import InMemoryWorkspace
from remora_demo.companion.agents.analyzers.question_generator import (
    QuestionGenerator,
    QuestionGeneratorConfig,
)
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import (
    Connection,
    Question,
    SimilarResult,
    Structure,
)


@pytest.fixture
def workspace() -> InMemoryWorkspace:
    return InMemoryWorkspace()


@pytest.fixture
def generator(workspace: InMemoryWorkspace) -> QuestionGenerator:
    return QuestionGenerator(workspace, config=QuestionGeneratorConfig(debounce_ms=0))


# -- Construction --


class TestQuestionGeneratorInit:
    def test_creates_with_defaults(self, workspace: InMemoryWorkspace) -> None:
        agent = QuestionGenerator(workspace)
        assert agent.name == "question_generator"

    def test_creates_with_custom_config(self, workspace: InMemoryWorkspace) -> None:
        cfg = QuestionGeneratorConfig(max_questions=3)
        agent = QuestionGenerator(workspace, config=cfg)
        assert agent.config.max_questions == 3

    def test_has_subscriptions(self, generator: QuestionGenerator) -> None:
        targets = [s.target for s in generator.subscriptions]
        assert "/companion/context/*" in targets
        assert "/companion/analysis/connections/*" in targets


# -- Question generation from connections --


class TestConnectionQuestions:
    async def test_test_connection_generates_question(
        self, workspace: InMemoryWorkspace, generator: QuestionGenerator
    ) -> None:
        """A test connection should generate a question about test coverage."""
        await workspace.write("/companion/context/file_path", "src/processor.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="function", name="process_batch", parent="DataProcessor"),
        )
        await workspace.write(
            "/companion/analysis/connections/0",
            Connection(
                from_file="src/processor.py",
                to_file="tests/test_processor.py",
                insight="Has tests in test_processor.py",
                connection_type="tested_by",
            ),
        )

        change = PathChanged(path="/companion/analysis/connections/0", value=None)
        await generator.on_connection_change(change)

        questions = await _read_questions(workspace)
        assert len(questions) >= 1
        # Should have a question related to tests
        test_q = [q for q in questions if "test" in q.question.lower()]
        assert len(test_q) >= 1

    async def test_doc_connection_generates_question(
        self, workspace: InMemoryWorkspace, generator: QuestionGenerator
    ) -> None:
        """A documentation connection should generate a question about doc accuracy."""
        await workspace.write("/companion/context/file_path", "src/processor.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="class", name="DataProcessor"),
        )
        await workspace.write(
            "/companion/analysis/connections/0",
            Connection(
                from_file="src/processor.py",
                to_file="docs/architecture.md",
                insight="Documented in architecture.md",
                connection_type="documented_by",
            ),
        )

        change = PathChanged(path="/companion/analysis/connections/0", value=None)
        await generator.on_connection_change(change)

        questions = await _read_questions(workspace)
        assert len(questions) >= 1
        doc_q = [q for q in questions if "doc" in q.question.lower() or "updat" in q.question.lower()]
        assert len(doc_q) >= 1


# -- Question generation from context --


class TestContextQuestions:
    async def test_function_context_generates_question(
        self, workspace: InMemoryWorkspace, generator: QuestionGenerator
    ) -> None:
        """Being in a function should generate relevant questions."""
        await workspace.write("/companion/context/file_path", "src/processor.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="function", name="process_batch", parent="DataProcessor"),
        )

        change = PathChanged(path="/companion/context/structure", value=None)
        await generator.on_context_change(change)

        questions = await _read_questions(workspace)
        assert len(questions) >= 1

    async def test_heading_context_generates_question(
        self, workspace: InMemoryWorkspace, generator: QuestionGenerator
    ) -> None:
        """Being in a markdown heading should generate relevant questions."""
        await workspace.write("/companion/context/file_path", "docs/architecture.md")
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="heading", name="Error Handling", depth=2),
        )

        change = PathChanged(path="/companion/context/structure", value=None)
        await generator.on_context_change(change)

        questions = await _read_questions(workspace)
        assert len(questions) >= 1


# -- Limits --


class TestQuestionLimits:
    async def test_respects_max_questions(self, workspace: InMemoryWorkspace) -> None:
        cfg = QuestionGeneratorConfig(debounce_ms=0, max_questions=2)
        agent = QuestionGenerator(workspace, config=cfg)

        await workspace.write("/companion/context/file_path", "src/processor.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="function", name="process_batch", parent="DataProcessor"),
        )
        # Add multiple connections to generate many questions
        for i in range(5):
            await workspace.write(
                f"/companion/analysis/connections/{i}",
                Connection(
                    from_file="src/processor.py",
                    to_file=f"src/other_{i}.py",
                    insight=f"Similar pattern in other_{i}.py",
                    connection_type="similar",
                ),
            )

        change = PathChanged(path="/companion/analysis/connections/0", value=None)
        await agent.on_connection_change(change)

        questions = await _read_questions(workspace)
        assert len(questions) <= 2

    async def test_clears_old_questions_on_refresh(
        self, workspace: InMemoryWorkspace, generator: QuestionGenerator
    ) -> None:
        """Old questions should be cleared when new ones are generated."""
        # Pre-populate stale questions
        await workspace.write(
            "/companion/analysis/questions/0",
            Question(question="Old question?", priority="low", context="stale"),
        )

        await workspace.write("/companion/context/file_path", "src/new_file.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="function", name="new_func"),
        )

        change = PathChanged(path="/companion/context/structure", value=None)
        await generator.on_context_change(change)

        questions = await _read_questions(workspace)
        # All questions should be fresh, not the old "Old question?"
        old_qs = [q for q in questions if q.question == "Old question?"]
        assert len(old_qs) == 0


# -- Activation tracking --


class TestQuestionActivation:
    async def test_records_activation(self, workspace: InMemoryWorkspace, generator: QuestionGenerator) -> None:
        await workspace.write("/companion/context/file_path", "src/main.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="function", name="main"),
        )

        change = PathChanged(path="/companion/context/structure", value=None)
        await generator.on_context_change(change)

        assert len(generator.activations) >= 1
        last = generator.activations[-1]
        assert last.agent_name == "question_generator"
        assert last.status == "success"


# -- Helpers --


async def _read_questions(workspace: InMemoryWorkspace) -> list[Question]:
    paths = await workspace.list("/companion/analysis/questions/*")
    questions = []
    for p in paths:
        val = await workspace.read(p)
        if isinstance(val, Question):
            questions.append(val)
    return questions
