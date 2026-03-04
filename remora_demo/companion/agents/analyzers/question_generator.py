"""Question generator analyzer agent.

Generates contextual questions based on the user's current context
and discovered connections. Writes Question objects to
/companion/analysis/questions/*.

Subscribes to: /companion/context/*, /companion/analysis/connections/*
Reads: /companion/context/file_path, /companion/context/content_type,
       /companion/context/structure, /companion/analysis/connections/*
Writes to: /companion/analysis/questions/*
"""

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora_demo.companion.agents.base import (
    AgentActivation,
    AgentBase,
    WorkspaceInterface,
    subscribe,
)
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import Connection, Question, Structure


@dataclass
class QuestionGeneratorConfig:
    """Configuration for question generator."""

    debounce_ms: int = 300
    max_questions: int = 5


class QuestionGenerator(AgentBase):
    """Generates contextual questions based on context and connections.

    Produces questions that help the user think about:
    - Test coverage for the code they're looking at
    - Whether documentation is up to date
    - Edge cases in the current function
    - Connections they might have missed
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: QuestionGeneratorConfig | None = None,
    ) -> None:
        super().__init__("question_generator")
        self.workspace = workspace
        self.config = config or QuestionGeneratorConfig()

    @subscribe("/companion/context/*", debounce_ms=300)
    async def on_context_change(self, change: PathChanged) -> None:
        """Regenerate questions when context changes."""
        await self._generate_questions()

    @subscribe("/companion/analysis/connections/*", debounce_ms=300)
    async def on_connection_change(self, change: PathChanged) -> None:
        """Regenerate questions when connections change."""
        await self._generate_questions()

    async def _generate_questions(self) -> None:
        """Generate questions and write them to workspace."""
        activation = AgentActivation(
            id=str(uuid.uuid4())[:8],
            agent_name=self.name,
            trigger="/companion/analysis/questions",
            started_at=time.time(),
            status="running",
        )
        self._activations.append(activation)

        try:
            await self._do_generate()
            activation.status = "success"
        except Exception as e:
            activation.status = "error"
            activation.error = str(e)
            raise
        finally:
            activation.ended_at = time.time()

    async def _do_generate(self) -> None:
        """Core question generation logic."""
        file_path = await self.workspace.read("/companion/context/file_path")
        content_type = await self.workspace.read("/companion/context/content_type")
        structure: Structure | None = await self.workspace.read("/companion/context/structure")

        if not file_path:
            return

        self.record_input("/companion/context/file_path", file_path)

        # Collect connections
        conn_paths = await self.workspace.list("/companion/analysis/connections/*")
        connections: list[Connection] = []
        for path in conn_paths:
            val = await self.workspace.read(path)
            if isinstance(val, Connection):
                connections.append(val)

        # Generate questions from various sources
        questions: list[Question] = []

        # Questions from connections
        for conn in connections:
            conn_qs = self._questions_from_connection(conn, structure)
            questions.extend(conn_qs)

        # Questions from context
        ctx_qs = self._questions_from_context(file_path, content_type, structure)
        questions.extend(ctx_qs)

        # Deduplicate by question text
        seen: set[str] = set()
        unique: list[Question] = []
        for q in questions:
            if q.question not in seen:
                seen.add(q.question)
                unique.append(q)

        # Limit
        unique = unique[: self.config.max_questions]

        # Clear old questions
        old_paths = await self.workspace.list("/companion/analysis/questions/*")
        for path in old_paths:
            await self.workspace.delete(path)

        # Write new questions
        for i, q in enumerate(unique):
            path = f"/companion/analysis/questions/{i}"
            await self.workspace.write(path, q)
            self.record_output(path)

    def _questions_from_connection(self, conn: Connection, structure: Structure | None) -> list[Question]:
        """Generate questions from a single connection."""
        questions: list[Question] = []
        to_name = Path(conn.to_file).name

        if conn.connection_type in ("tested_by", "tests"):
            struct_desc = f"'{structure.name}'" if structure else "this code"
            questions.append(
                Question(
                    question=f"Are the tests in {to_name} up to date with recent changes to {struct_desc}?",
                    priority="medium",
                    context=conn.insight,
                )
            )

        elif conn.connection_type in ("documented_by", "documents"):
            questions.append(
                Question(
                    question=f"Does the documentation in {to_name} still accurately describe the current implementation?",
                    priority="medium",
                    context=conn.insight,
                )
            )

        elif conn.connection_type == "similar":
            questions.append(
                Question(
                    question=f"Could the similar pattern in {to_name} be unified with this implementation?",
                    priority="low",
                    context=conn.insight,
                )
            )

        elif conn.connection_type == "references":
            questions.append(
                Question(
                    question=f"Are the concepts referenced in {to_name} consistent with this code?",
                    priority="low",
                    context=conn.insight,
                )
            )

        return questions

    def _questions_from_context(
        self,
        file_path: str,
        content_type: str | None,
        structure: Structure | None,
    ) -> list[Question]:
        """Generate questions from the current context alone."""
        questions: list[Question] = []
        file_name = Path(file_path).name

        if content_type == "code" and structure:
            if structure.structure_type == "function":
                questions.append(
                    Question(
                        question=f"What edge cases should '{structure.name}' handle?",
                        priority="medium",
                        context=f"Currently in function {structure.name} in {file_name}",
                    )
                )
                if structure.parent:
                    questions.append(
                        Question(
                            question=f"Does '{structure.name}' follow the same patterns as other methods in {structure.parent}?",
                            priority="low",
                            context=f"Method of class {structure.parent}",
                        )
                    )

            elif structure.structure_type == "class":
                questions.append(
                    Question(
                        question=f"Is the responsibility of '{structure.name}' well-defined, or is it doing too much?",
                        priority="low",
                        context=f"Currently in class {structure.name} in {file_name}",
                    )
                )

        elif content_type == "markdown" and structure:
            if structure.structure_type == "heading":
                questions.append(
                    Question(
                        question=f"Is the section '{structure.name}' complete and accurate?",
                        priority="medium",
                        context=f"Currently in heading '{structure.name}' in {file_name}",
                    )
                )

        return questions

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, PathChanged):
            if data.path.startswith("/companion/analysis/connections/"):
                await self.on_connection_change(data)
            else:
                await self.on_context_change(data)
