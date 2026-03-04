"""Session clock sensor agent.

Emits periodic SessionTick events for time-based triggers.
"""

import asyncio
import time
from dataclasses import dataclass

from remora_demo.companion.models.events import SessionTick


@dataclass
class SessionClockConfig:
    """Configuration for session clock."""

    tick_interval_ms: int = 30000  # 30 seconds between ticks


class SessionClock:
    """Session clock sensor.

    Emits periodic ticks that can be used for:
    - Session summaries
    - Periodic state cleanup
    - Time-based analysis triggers

    Usage:
        clock = SessionClock(config)
        clock.on_event = lambda e: print(f"Tick: {e.tick_number}")

        await clock.start()
        # ... later ...
        await clock.stop()
    """

    def __init__(self, config: SessionClockConfig | None = None) -> None:
        self.config = config or SessionClockConfig()
        self._start_time: float | None = None
        self._tick_number = 0
        self._task: asyncio.Task | None = None
        self._running = False
        self._event_handlers: list[callable] = []

    def on_event(self, handler: callable) -> None:
        """Register an event handler for SessionTick events."""
        self._event_handlers.append(handler)

    async def _emit(self, event: SessionTick) -> None:
        """Emit event to all registered handlers."""
        for handler in self._event_handlers:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result

    async def start(self) -> None:
        """Start the clock."""
        if self._running:
            return

        self._running = True
        self._start_time = time.time() * 1000
        self._tick_number = 0
        self._task = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        """Stop the clock."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _tick_loop(self) -> None:
        """Background loop to emit ticks."""
        while self._running:
            try:
                await asyncio.sleep(self.config.tick_interval_ms / 1000)

                if not self._running:
                    break

                self._tick_number += 1
                elapsed = int(time.time() * 1000 - self._start_time)

                event = SessionTick(
                    elapsed_ms=elapsed,
                    tick_number=self._tick_number,
                )
                await self._emit(event)

            except asyncio.CancelledError:
                break
            except Exception:
                # Don't crash the loop on errors
                pass

    @property
    def elapsed_ms(self) -> int:
        """Get elapsed time since session start."""
        if self._start_time is None:
            return 0
        return int(time.time() * 1000 - self._start_time)

    @property
    def tick_number(self) -> int:
        """Get current tick number."""
        return self._tick_number
