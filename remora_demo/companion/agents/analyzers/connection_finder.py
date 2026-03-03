"""Connection finder analyzer agent.

This is the "magic" agent that discovers non-obvious connections between:
- Code and documentation
- Functions and their tests
- Similar implementations across files
- Concepts mentioned in code and explained in notes

Subscribes to: /companion/search/similar/*, /companion/context/*
Writes to: /companion/analysis/connections/*
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora_demo.companion.agents.base import AgentBase, WorkspaceInterface, subscribe
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import Connection, SimilarResult, Structure


@dataclass
class ConnectionFinderConfig:
    """Configuration for connection finder."""

    max_connections: int = 5
    min_confidence: float = 0.3
    # Patterns for detecting connection types
    test_patterns: list[str] | None = None
    doc_patterns: list[str] | None = None

    def __post_init__(self) -> None:
        if self.test_patterns is None:
            self.test_patterns = ["test_", "_test.py", "tests/", "spec_", "_spec."]
        if self.doc_patterns is None:
            self.doc_patterns = [".md", "docs/", "README", "NOTES", ".rst"]


class ConnectionFinder(AgentBase):
    """Analyzes search results and context to find meaningful connections.

    This agent looks for patterns that indicate relationships:
    - test_foo.py <-> foo.py (test relationship)
    - foo.py <-> docs/foo.md (documentation)
    - Similar function signatures (parallel implementations)
    - Shared terminology (concept connections)
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: ConnectionFinderConfig | None = None,
    ) -> None:
        super().__init__("connection_finder")
        self.workspace = workspace
        self.config = config or ConnectionFinderConfig()
        self._pending_analysis = False

    @subscribe("/companion/search/similar/*", debounce_ms=300)
    async def on_search_results(self, change: PathChanged) -> None:
        """Analyze when new search results arrive."""
        if not self._pending_analysis:
            self._pending_analysis = True
            # Slight delay to batch multiple result updates
            await self._analyze_connections()
            self._pending_analysis = False

    async def _analyze_connections(self) -> None:
        """Analyze current context and search results to find connections."""
        # Get current context
        file_path = await self.workspace.read("/companion/context/file_path")
        structure = await self.workspace.read("/companion/context/structure")
        content_type = await self.workspace.read("/companion/context/content_type")

        if not file_path:
            return

        # Record inputs
        self.record_input("/companion/context/file_path", file_path)

        # Get search results
        similar_paths = await self.workspace.list("/companion/search/similar/*")
        similar_results: list[SimilarResult] = []
        for path in similar_paths:
            result = await self.workspace.read(path)
            if isinstance(result, SimilarResult):
                similar_results.append(result)

        # Find connections
        connections: list[Connection] = []

        # 1. Test-implementation connections
        test_connections = self._find_test_connections(file_path, similar_results)
        connections.extend(test_connections)

        # 2. Documentation connections
        doc_connections = self._find_doc_connections(file_path, similar_results, structure)
        connections.extend(doc_connections)

        # 3. Parallel implementation connections
        impl_connections = self._find_parallel_implementations(file_path, similar_results, structure)
        connections.extend(impl_connections)

        # 4. Concept connections (code referencing same concepts)
        concept_connections = self._find_concept_connections(file_path, similar_results, content_type)
        connections.extend(concept_connections)

        # Deduplicate and limit
        seen = set()
        unique_connections = []
        for conn in connections:
            key = (conn.from_file, conn.to_file, conn.connection_type)
            if key not in seen:
                seen.add(key)
                unique_connections.append(conn)

        unique_connections = unique_connections[: self.config.max_connections]

        # Clear old connections
        old_paths = await self.workspace.list("/companion/analysis/connections/*")
        for path in old_paths:
            await self.workspace.delete(path)

        # Write new connections
        for i, conn in enumerate(unique_connections):
            path = f"/companion/analysis/connections/{i}"
            await self.workspace.write(path, conn)
            self.record_output(path)

    def _find_test_connections(self, current_file: str, similar: list[SimilarResult]) -> list[Connection]:
        """Find test<->implementation connections."""
        connections = []
        current_path = Path(current_file)
        current_stem = current_path.stem

        # Check if current file is a test
        is_test = any(p in current_file for p in self.config.test_patterns or [])

        for result in similar:
            result_path = Path(result.file)
            result_stem = result_path.stem

            # Check if result is a test
            result_is_test = any(p in result.file for p in self.config.test_patterns or [])

            # Test <-> Implementation connection
            if is_test != result_is_test:
                # Check for name similarity
                if self._names_related(current_stem, result_stem):
                    if is_test:
                        connections.append(
                            Connection(
                                from_file=current_file,
                                to_file=result.file,
                                insight=f"Tests implementation in {result_path.name}",
                                connection_type="tests",
                            )
                        )
                    else:
                        connections.append(
                            Connection(
                                from_file=current_file,
                                to_file=result.file,
                                insight=f"Has tests in {result_path.name}",
                                connection_type="tested_by",
                            )
                        )

        return connections

    def _find_doc_connections(
        self,
        current_file: str,
        similar: list[SimilarResult],
        structure: Structure | None,
    ) -> list[Connection]:
        """Find documentation connections."""
        connections = []
        current_path = Path(current_file)
        current_stem = current_path.stem

        # Check if current file is documentation
        is_doc = any(p in current_file for p in self.config.doc_patterns or [])

        for result in similar:
            result_path = Path(result.file)

            # Check if result is documentation
            result_is_doc = any(p in result.file for p in self.config.doc_patterns or [])

            if is_doc != result_is_doc:
                # Code <-> Documentation connection
                if result.score > 0.5:  # Higher threshold for doc connections
                    if is_doc:
                        connections.append(
                            Connection(
                                from_file=current_file,
                                to_file=result.file,
                                insight=f"Documents code in {result_path.name}",
                                connection_type="documents",
                            )
                        )
                    else:
                        # Look for specific structure mentions
                        structure_name = structure.name if structure else current_stem
                        connections.append(
                            Connection(
                                from_file=current_file,
                                to_file=result.file,
                                insight=f"Documented in {result_path.name}",
                                connection_type="documented_by",
                            )
                        )

        return connections

    def _find_parallel_implementations(
        self,
        current_file: str,
        similar: list[SimilarResult],
        structure: Structure | None,
    ) -> list[Connection]:
        """Find similar implementations (e.g., same pattern in different modules)."""
        connections = []

        if not structure or structure.structure_type not in ("function", "class"):
            return connections

        for result in similar:
            # Same content type, high similarity, different file
            if result.content_type == "code" and result.score > 0.7 and result.file != current_file:
                # Check if snippet contains similar structure
                if structure.name.lower() in result.snippet.lower():
                    connections.append(
                        Connection(
                            from_file=current_file,
                            to_file=result.file,
                            insight=f"Similar {structure.structure_type} pattern",
                            connection_type="similar",
                        )
                    )
                elif self._detect_similar_pattern(structure, result.snippet):
                    result_path = Path(result.file)
                    connections.append(
                        Connection(
                            from_file=current_file,
                            to_file=result.file,
                            insight=f"Parallel implementation in {result_path.name}",
                            connection_type="similar",
                        )
                    )

        return connections

    def _find_concept_connections(
        self,
        current_file: str,
        similar: list[SimilarResult],
        content_type: str | None,
    ) -> list[Connection]:
        """Find connections based on shared concepts/terminology."""
        connections = []

        # Only look for concept connections in code
        if content_type != "code":
            return connections

        for result in similar:
            # markdown results with good scores are potential concept connections
            if result.content_type == "markdown" and result.score > 0.4:
                result_path = Path(result.file)
                connections.append(
                    Connection(
                        from_file=current_file,
                        to_file=result.file,
                        insight=f"Related concepts in {result_path.name}",
                        connection_type="references",
                    )
                )

        return connections

    def _names_related(self, name1: str, name2: str) -> bool:
        """Check if two names are related (e.g., 'foo' and 'test_foo')."""
        # Remove common prefixes/suffixes
        clean1 = name1.replace("test_", "").replace("_test", "").replace("spec_", "").replace("_spec", "")
        clean2 = name2.replace("test_", "").replace("_test", "").replace("spec_", "").replace("_spec", "")

        return clean1 == clean2 or clean1 in clean2 or clean2 in clean1

    def _detect_similar_pattern(self, structure: Structure, snippet: str) -> bool:
        """Detect if a snippet has a similar pattern to current structure."""
        # Simple heuristics for pattern detection
        if structure.structure_type == "function":
            # Look for similar function definitions
            if "def " in snippet or "async def " in snippet:
                # Check for similar parameter patterns
                # This is a simple heuristic - could be enhanced with AST
                return True

        if structure.structure_type == "class":
            if "class " in snippet:
                return True

        return False

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, PathChanged):
            await self.on_search_results(data)
