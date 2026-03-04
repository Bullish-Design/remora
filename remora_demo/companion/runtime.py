"""Companion runtime: orchestrates agents and manages the reactive loop."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from remora_demo.companion.agents.analyzers import (
    ConnectionFinder,
    QuestionGenerator,
    TaskInferrer,
)
from remora_demo.companion.agents.base import InMemoryWorkspace, WorkspaceInterface
from remora_demo.companion.agents.composers import SidebarComposer
from remora_demo.companion.agents.extractors import ContextExtractor, EditSummarizer
from remora_demo.companion.agents.searchers import EmbeddingSearcher
from remora_demo.companion.agents.sensors import (
    CursorTracker,
    EditTracker,
    FileWatcher,
    FileWatcherConfig,
    SessionClock,
)
from remora_demo.companion.indexing import IndexConfig, Indexer
from remora_demo.companion.models.events import ContentEdited, CursorMoved, FileChanged, PathChanged

logger = logging.getLogger(__name__)


@dataclass
class CompanionConfig:
    """Configuration for Companion runtime."""

    # Indexing
    workspace_path: Path = field(default_factory=Path.cwd)
    db_path: Path = field(default_factory=lambda: Path(".companion/index.db"))
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"

    # Output
    sidebar_output_path: Path | None = None  # If set, write sidebar to this file

    # Behavior
    auto_index: bool = True  # Index workspace on startup
    linger_threshold_ms: int = 3000


class CompanionRuntime:
    """Main runtime for Companion.

    Wires together all agents and manages the reactive loop.

    Usage:
        runtime = CompanionRuntime(config)
        await runtime.start()

        # Simulate cursor movement (normally from LSP)
        await runtime.on_cursor_moved("src/main.py", 42, 0)

        # Get composed sidebar
        sidebar = await runtime.get_sidebar()

        await runtime.stop()
    """

    def __init__(self, config: CompanionConfig | None = None) -> None:
        self.config = config or CompanionConfig()
        self._workspace: WorkspaceInterface | None = None
        self._indexer: Indexer | None = None
        self._running = False

        # Sensors
        self._cursor_tracker: CursorTracker | None = None
        self._edit_tracker: EditTracker | None = None
        self._file_watcher: FileWatcher | None = None
        self._session_clock: SessionClock | None = None

        # Agents
        self._context_extractor: ContextExtractor | None = None
        self._edit_summarizer: EditSummarizer | None = None
        self._embedding_searcher: EmbeddingSearcher | None = None
        self._connection_finder: ConnectionFinder | None = None
        self._task_inferrer: TaskInferrer | None = None
        self._question_generator: QuestionGenerator | None = None
        self._sidebar_composer: SidebarComposer | None = None

    @property
    def workspace(self) -> WorkspaceInterface:
        """Get the workspace."""
        if self._workspace is None:
            self._workspace = InMemoryWorkspace()
        return self._workspace

    @property
    def indexer(self) -> Indexer:
        """Get the indexer."""
        if self._indexer is None:
            index_config = IndexConfig(
                db_path=self.config.db_path,
            )
            index_config.embedding.model_name = self.config.embedding_model
            self._indexer = Indexer(index_config)
        return self._indexer

    async def start(self) -> None:
        """Start the Companion runtime."""
        if self._running:
            return

        logger.info("Starting Companion runtime...")

        # Auto-index workspace if configured
        if self.config.auto_index:
            logger.info(f"Indexing workspace: {self.config.workspace_path}")
            stats = self.indexer.index_directory(self.config.workspace_path)
            logger.info(f"Indexed {stats['total_chunks']} chunks from {stats['total_files']} files")

        # Initialize sensors
        self._cursor_tracker = CursorTracker()
        self._edit_tracker = EditTracker()
        self._file_watcher = FileWatcher(FileWatcherConfig(watch_path=self.config.workspace_path))
        self._session_clock = SessionClock()

        # Initialize agents
        self._context_extractor = ContextExtractor(self.workspace)
        self._edit_summarizer = EditSummarizer(self.workspace)
        self._embedding_searcher = EmbeddingSearcher(self.workspace, self.indexer)
        self._connection_finder = ConnectionFinder(self.workspace)
        self._task_inferrer = TaskInferrer(self.workspace)
        self._question_generator = QuestionGenerator(self.workspace)
        self._sidebar_composer = SidebarComposer(self.workspace)

        # Wire up event flow
        self._cursor_tracker.on_event(self._on_cursor_event)
        self._edit_tracker.on_event(self._on_content_edited_event)
        self._file_watcher.on_event(self._on_file_changed)

        # Set up workspace listeners for agent-to-agent communication
        if isinstance(self.workspace, InMemoryWorkspace):
            self.workspace.add_listener(self._on_path_change)

        # Start background tasks
        await self._cursor_tracker.start_linger_detection()
        await self._file_watcher.start()
        await self._session_clock.start()

        self._running = True
        logger.info("Companion runtime started")

    async def stop(self) -> None:
        """Stop the Companion runtime."""
        if not self._running:
            return

        logger.info("Stopping Companion runtime...")

        if self._cursor_tracker:
            await self._cursor_tracker.stop()
        if self._edit_tracker:
            await self._edit_tracker.stop()
        if self._file_watcher:
            await self._file_watcher.stop()
        if self._session_clock:
            await self._session_clock.stop()
        if self._indexer:
            self._indexer.close()

        self._running = False
        logger.info("Companion runtime stopped")

    async def _on_cursor_event(self, event: CursorMoved) -> None:
        """Handle cursor events from sensor."""
        # Forward to context extractor
        if self._context_extractor:
            await self._context_extractor.handle_event(event)

    async def _on_content_edited_event(self, event: ContentEdited) -> None:
        """Handle content edited events from edit tracker sensor."""
        if self._edit_summarizer:
            await self._edit_summarizer.on_content_edited(event)

    async def _on_file_changed(self, event: FileChanged) -> None:
        """Handle file change events from file watcher sensor."""
        logger.debug("File changed: %s (%s)", event.path, event.kind)
        # Could trigger re-indexing or notify other agents in the future

    async def _on_path_change(self, change: PathChanged) -> None:
        """Handle workspace path changes for agent-to-agent communication."""
        # Forward to embedding searcher
        if self._embedding_searcher and change.path.startswith("/companion/context/"):
            await self._embedding_searcher.handle_path_change(change)

        # Forward to connection finder
        if self._connection_finder and change.path.startswith("/companion/search/"):
            await self._connection_finder.handle_path_change(change)

        # Forward to task inferrer (watches context changes)
        if self._task_inferrer and change.path.startswith("/companion/context/"):
            await self._task_inferrer.on_context_change(change)

        # Forward to question generator (watches context and connections)
        if self._question_generator:
            if change.path.startswith("/companion/context/"):
                await self._question_generator.on_context_change(change)
            elif change.path.startswith("/companion/analysis/connections/"):
                await self._question_generator.on_connection_change(change)

        # Forward to sidebar composer
        if self._sidebar_composer:
            if (
                change.path.startswith("/companion/context/")
                or change.path.startswith("/companion/search/")
                or change.path.startswith("/companion/analysis/")
            ):
                await self._sidebar_composer.handle_path_change(change)

        # Write sidebar to file if configured
        if self.config.sidebar_output_path and change.path == "/companion/output/sidebar.md":
            try:
                self.config.sidebar_output_path.parent.mkdir(parents=True, exist_ok=True)
                self.config.sidebar_output_path.write_text(change.value)
            except Exception as e:
                logger.error(f"Failed to write sidebar: {e}")

    # Public API for external triggers (e.g., from LSP server)

    async def on_cursor_moved(self, file: str, line: int, col: int) -> None:
        """Handle cursor movement from editor."""
        if self._cursor_tracker:
            await self._cursor_tracker.handle_cursor_notification(file, line, col)

    async def on_content_edited(self, file: str, start_line: int, end_line: int, text: str) -> None:
        """Handle content edit from editor."""
        if self._edit_tracker:
            await self._edit_tracker.handle_content_change(file, start_line, end_line, text)

    async def get_sidebar(self) -> str | None:
        """Get the current sidebar markdown."""
        return await self.workspace.read("/companion/output/sidebar.md")

    async def get_context(self) -> dict[str, Any]:
        """Get the current context state."""
        return {
            "file_path": await self.workspace.read("/companion/context/file_path"),
            "cursor_position": await self.workspace.read("/companion/context/cursor_position"),
            "content_type": await self.workspace.read("/companion/context/content_type"),
            "structure": await self.workspace.read("/companion/context/structure"),
        }

    def get_activations(self) -> list[dict]:
        """Get all agent activations for timeline visualization."""
        activations = []

        for agent in [
            self._context_extractor,
            self._edit_summarizer,
            self._embedding_searcher,
            self._connection_finder,
            self._task_inferrer,
            self._question_generator,
            self._sidebar_composer,
        ]:
            if agent:
                for act in agent.activations:
                    activations.append(
                        {
                            "id": act.id,
                            "agent": act.agent_name,
                            "trigger": act.trigger,
                            "started_at": act.started_at,
                            "ended_at": act.ended_at,
                            "status": act.status,
                            "inputs": act.inputs,
                            "outputs": act.outputs,
                        }
                    )

        # Sort by start time
        activations.sort(key=lambda a: a["started_at"])
        return activations
