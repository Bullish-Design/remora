"""Cursor tracking sensor agent.

Watches for cursor position changes from the editor (via LSP)
and emits CursorMoved events with debouncing.
"""

import asyncio
import time
from dataclasses import dataclass, field

from remora_demo.companion.models.events import CursorMoved


@dataclass
class CursorState:
    """Track cursor state for linger detection."""

    file: str
    line: int
    col: int
    timestamp: float
    notified_linger: bool = False


@dataclass
class CursorTrackerConfig:
    """Configuration for cursor tracker."""

    debounce_ms: int = 100  # Debounce rapid movements
    linger_threshold_ms: int = 3000  # Time to consider "lingering"
    linger_check_interval_ms: int = 500  # How often to check for linger


class CursorTracker:
    """Cursor tracking sensor.

    This is an edge sensor that receives raw cursor events from the editor
    and emits debounced CursorMoved events. It also detects "lingering"
    when the cursor stays in one place for an extended time.

    Usage:
        tracker = CursorTracker(config)
        tracker.on_event = lambda e: print(f"Cursor moved: {e}")

        # Called by LSP server when cursor notification received
        await tracker.handle_cursor_notification(file, line, col)
    """

    def __init__(self, config: CursorTrackerConfig | None = None) -> None:
        self.config = config or CursorTrackerConfig()
        self._current_state: CursorState | None = None
        self._debounce_task: asyncio.Task | None = None
        self._linger_task: asyncio.Task | None = None
        self._event_handlers: list[callable] = []
        self._running = False

    def on_event(self, handler: callable) -> None:
        """Register an event handler for CursorMoved events."""
        self._event_handlers.append(handler)

    async def _emit(self, event: CursorMoved) -> None:
        """Emit event to all registered handlers."""
        for handler in self._event_handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    async def handle_cursor_notification(self, file: str, line: int, col: int) -> None:
        """Handle raw cursor notification from editor.

        This is called by the LSP server when it receives a cursor
        position notification from the editor.
        """
        now = time.time() * 1000  # ms

        # Check if position actually changed
        if self._current_state:
            if self._current_state.file == file and self._current_state.line == line and self._current_state.col == col:
                return  # No change

        # Update state
        self._current_state = CursorState(
            file=file,
            line=line,
            col=col,
            timestamp=now,
            notified_linger=False,
        )

        # Cancel existing debounce
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        # Start debounce timer
        self._debounce_task = asyncio.create_task(self._debounced_emit(file, line, col))

    async def _debounced_emit(self, file: str, line: int, col: int) -> None:
        """Emit event after debounce period."""
        try:
            await asyncio.sleep(self.config.debounce_ms / 1000)

            # Verify state hasn't changed during debounce
            if (
                self._current_state
                and self._current_state.file == file
                and self._current_state.line == line
                and self._current_state.col == col
            ):
                event = CursorMoved(file=file, line=line, col=col, lingered=False)
                await self._emit(event)

        except asyncio.CancelledError:
            pass  # Debounce cancelled by new movement

    async def start_linger_detection(self) -> None:
        """Start the background linger detection loop."""
        self._running = True
        self._linger_task = asyncio.create_task(self._linger_loop())

    async def stop(self) -> None:
        """Stop the tracker."""
        self._running = False
        if self._linger_task:
            self._linger_task.cancel()
            try:
                await self._linger_task
            except asyncio.CancelledError:
                pass
        if self._debounce_task:
            self._debounce_task.cancel()

    async def _linger_loop(self) -> None:
        """Background loop to detect lingering."""
        while self._running:
            try:
                await asyncio.sleep(self.config.linger_check_interval_ms / 1000)

                if not self._current_state:
                    continue

                if self._current_state.notified_linger:
                    continue

                now = time.time() * 1000
                elapsed = now - self._current_state.timestamp

                if elapsed >= self.config.linger_threshold_ms:
                    # Cursor has lingered
                    self._current_state.notified_linger = True
                    event = CursorMoved(
                        file=self._current_state.file,
                        line=self._current_state.line,
                        col=self._current_state.col,
                        lingered=True,
                    )
                    await self._emit(event)

            except asyncio.CancelledError:
                break
            except Exception:
                # Don't crash the loop on errors
                pass

    @property
    def current_position(self) -> tuple[str, int, int] | None:
        """Get current cursor position."""
        if self._current_state:
            return (
                self._current_state.file,
                self._current_state.line,
                self._current_state.col,
            )
        return None
