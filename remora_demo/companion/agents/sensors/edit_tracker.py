"""Edit tracking sensor agent.

Watches for content edits from the editor (via LSP didChange)
and emits ContentEdited events with coalescing.
"""

import asyncio
import time
from dataclasses import dataclass, field

from remora_demo.companion.models.events import ContentEdited


@dataclass
class PendingEdit:
    """Accumulated edit state for coalescing."""

    file: str
    start_line: int
    end_line: int
    text: str
    timestamp: float


@dataclass
class EditTrackerConfig:
    """Configuration for edit tracker."""

    coalesce_ms: int = 500  # Time to wait before emitting coalesced edit
    max_coalesce_ms: int = 2000  # Maximum time to coalesce (force emit)


class EditTracker:
    """Edit tracking sensor.

    This is an edge sensor that receives raw content change events
    from the editor and emits coalesced ContentEdited events.

    Coalescing helps reduce noise from rapid typing while still
    capturing the overall edit intent.

    Usage:
        tracker = EditTracker(config)
        tracker.on_event = lambda e: print(f"Edit: {e}")

        # Called by LSP server when didChange received
        await tracker.handle_content_change(file, start_line, end_line, text)
    """

    def __init__(self, config: EditTrackerConfig | None = None) -> None:
        self.config = config or EditTrackerConfig()
        self._pending: dict[str, PendingEdit] = {}  # file -> pending edit
        self._first_edit_time: dict[str, float] = {}  # file -> first edit timestamp
        self._coalesce_tasks: dict[str, asyncio.Task] = {}
        self._event_handlers: list[callable] = []

    def on_event(self, handler: callable) -> None:
        """Register an event handler for ContentEdited events."""
        self._event_handlers.append(handler)

    async def _emit(self, event: ContentEdited) -> None:
        """Emit event to all registered handlers."""
        for handler in self._event_handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    async def handle_content_change(
        self,
        file: str,
        start_line: int,
        end_line: int,
        text: str,
    ) -> None:
        """Handle raw content change from editor.

        Called by LSP server when textDocument/didChange is received.
        """
        now = time.time() * 1000

        # Track first edit time for max coalesce limit
        if file not in self._first_edit_time:
            self._first_edit_time[file] = now

        # Check if we've exceeded max coalesce time
        first_time = self._first_edit_time[file]
        if now - first_time >= self.config.max_coalesce_ms:
            # Force emit current pending edit
            if file in self._pending:
                await self._emit_pending(file)
            self._first_edit_time[file] = now

        # Coalesce with existing pending edit
        if file in self._pending:
            pending = self._pending[file]
            # Expand the affected range
            pending.start_line = min(pending.start_line, start_line)
            pending.end_line = max(pending.end_line, end_line)
            # Keep latest text (could be smarter about merging)
            pending.text = text
            pending.timestamp = now
        else:
            self._pending[file] = PendingEdit(
                file=file,
                start_line=start_line,
                end_line=end_line,
                text=text,
                timestamp=now,
            )

        # Cancel existing coalesce timer
        if file in self._coalesce_tasks:
            task = self._coalesce_tasks[file]
            if not task.done():
                task.cancel()

        # Start new coalesce timer
        self._coalesce_tasks[file] = asyncio.create_task(self._coalesce_timer(file))

    async def _coalesce_timer(self, file: str) -> None:
        """Wait for coalesce period then emit."""
        try:
            await asyncio.sleep(self.config.coalesce_ms / 1000)
            await self._emit_pending(file)
        except asyncio.CancelledError:
            pass  # Cancelled by new edit

    async def _emit_pending(self, file: str) -> None:
        """Emit pending edit for a file."""
        if file not in self._pending:
            return

        pending = self._pending.pop(file)
        self._first_edit_time.pop(file, None)

        event = ContentEdited(
            file=pending.file,
            start_line=pending.start_line,
            end_line=pending.end_line,
            text=pending.text,
        )
        await self._emit(event)

    async def flush(self) -> None:
        """Flush all pending edits immediately."""
        files = list(self._pending.keys())
        for file in files:
            # Cancel timer
            if file in self._coalesce_tasks:
                task = self._coalesce_tasks[file]
                if not task.done():
                    task.cancel()
            # Emit
            await self._emit_pending(file)

    async def stop(self) -> None:
        """Stop the tracker and flush pending edits."""
        await self.flush()
        # Cancel all remaining tasks
        for task in self._coalesce_tasks.values():
            if not task.done():
                task.cancel()
