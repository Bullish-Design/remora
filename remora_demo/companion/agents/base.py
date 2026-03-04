"""Base agent class and subscription decorator for Companion.

This module provides the infrastructure for building reactive agents
that subscribe to events or workspace paths and write to workspace state.
"""

import asyncio
import fnmatch
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from remora_demo.companion.models.events import PathChanged

T = TypeVar("T")


@dataclass
class Subscription:
    """A subscription to an event type or workspace path pattern."""

    target: str | type  # Event type or path pattern (e.g., "/companion/context/*")
    debounce_ms: int = 0
    handler: Callable[..., Any] | None = None


@dataclass
class AgentActivation:
    """Record of a single agent activation for debugging/timeline."""

    id: str
    agent_name: str
    trigger: str
    started_at: float
    ended_at: float = 0.0
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    status: str = "pending"  # "pending" | "running" | "success" | "error"
    error: str | None = None


def subscribe(
    target: str | type,
    debounce_ms: int = 0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to mark a method as subscribing to an event or path.

    Args:
        target: Event type (e.g., CursorMoved) or path pattern (e.g., "/companion/context/*")
        debounce_ms: Minimum time between handler invocations

    Example:
        @subscribe(CursorMoved, debounce_ms=100)
        async def on_cursor_move(self, event: CursorMoved) -> None:
            ...

        @subscribe("/companion/context/current_region")
        async def on_region_change(self, change: PathChanged) -> None:
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Store subscription metadata on the function
        if not hasattr(func, "_subscriptions"):
            func._subscriptions = []  # type: ignore[attr-defined]
        func._subscriptions.append(  # type: ignore[attr-defined]
            Subscription(target=target, debounce_ms=debounce_ms, handler=func)
        )
        return func

    return decorator


class AgentBase(ABC):
    """Base class for all Companion agents.

    Agents are small, focused units that:
    1. Subscribe to events or workspace paths
    2. Process incoming data
    3. Write results to workspace paths

    Agents don't know about each other — they communicate only
    through workspace state, enabling emergent behavior.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__
        self._subscriptions: list[Subscription] = []
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}  # Pending debounced calls
        self._debounce_latest_data: dict[str, Any] = {}  # Latest data for debounced calls
        self._activations: list[AgentActivation] = []

        # Collect subscriptions from decorated methods
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if attr and hasattr(attr, "_subscriptions"):
                for sub in attr._subscriptions:
                    self._subscriptions.append(
                        Subscription(
                            target=sub.target,
                            debounce_ms=sub.debounce_ms,
                            handler=attr,
                        )
                    )

    @property
    def subscriptions(self) -> list[Subscription]:
        """Get all subscriptions for this agent."""
        return self._subscriptions

    @property
    def activations(self) -> list[AgentActivation]:
        """Get activation history for debugging."""
        return self._activations

    def matches_path(self, pattern: str, path: str) -> bool:
        """Check if a path matches a subscription pattern.

        Supports glob patterns like "/companion/search/*"
        """
        # Normalize patterns
        if not pattern.startswith("/"):
            return False
        return fnmatch.fnmatch(path, pattern)

    async def handle_event(self, event: Any) -> None:
        """Handle an incoming event.

        Finds matching subscriptions and invokes handlers,
        respecting debounce settings.
        """
        event_type = type(event)

        for sub in self._subscriptions:
            # Check if subscription matches this event type
            if isinstance(sub.target, type) and isinstance(event, sub.target):
                await self._invoke_handler(sub, event)

    async def handle_path_change(self, change: PathChanged) -> None:
        """Handle a workspace path change.

        Finds matching subscriptions and invokes handlers,
        respecting debounce settings.
        """
        for sub in self._subscriptions:
            # Check if subscription matches this path
            if isinstance(sub.target, str) and self.matches_path(sub.target, change.path):
                await self._invoke_handler(sub, change)

    async def _invoke_handler(self, sub: Subscription, data: Any) -> None:
        """Invoke a subscription handler with debouncing and activation tracking.

        Uses trailing-edge debouncing: waits for quiet period, then fires with latest data.
        This ensures all rapid updates complete before the handler runs.
        """
        if sub.handler is None:
            return

        handler_key = f"{sub.target}:{id(sub.handler)}"

        # If debouncing, use trailing-edge: schedule/reschedule delayed execution
        if sub.debounce_ms > 0:
            # Store latest data
            self._debounce_latest_data[handler_key] = data

            # Cancel any pending task for this handler
            if handler_key in self._debounce_tasks:
                self._debounce_tasks[handler_key].cancel()

            # Schedule new execution after debounce period
            async def delayed_invoke() -> None:
                await asyncio.sleep(sub.debounce_ms / 1000.0)
                latest_data = self._debounce_latest_data.pop(handler_key, data)
                await self._execute_handler(sub, latest_data)

            self._debounce_tasks[handler_key] = asyncio.create_task(delayed_invoke())
            return

        # No debouncing - execute immediately
        await self._execute_handler(sub, data)

    async def _execute_handler(self, sub: Subscription, data: Any) -> None:
        """Execute a handler with activation tracking."""
        if sub.handler is None:
            return

        # Create activation record
        activation = AgentActivation(
            id=str(uuid.uuid4())[:8],
            agent_name=self.name,
            trigger=str(sub.target),
            started_at=time.time(),
            status="running",
        )
        self._activations.append(activation)

        try:
            # Invoke handler
            result = sub.handler(data)
            if asyncio.iscoroutine(result):
                await result

            activation.status = "success"
        except Exception as e:
            activation.status = "error"
            activation.error = str(e)
            raise
        finally:
            activation.ended_at = time.time()

    @abstractmethod
    async def process(self, data: Any) -> None:
        """Process incoming data. Override in subclasses.

        This is an alternative to using @subscribe decorators
        for simple agents with a single handler.
        """
        pass

    def record_output(self, path: str) -> None:
        """Record that this agent wrote to a workspace path.

        Call this when writing to workspace to track outputs
        for the activation timeline.
        """
        if self._activations:
            self._activations[-1].outputs.append(path)

    def record_input(self, path: str, value: Any) -> None:
        """Record that this agent read from a workspace path.

        Call this when reading from workspace to track inputs
        for the activation timeline.
        """
        if self._activations:
            self._activations[-1].inputs[path] = value


class WorkspaceInterface(ABC):
    """Abstract interface for workspace operations.

    Agents use this interface to read/write workspace state.
    Implementations can use Cairn or other backends.
    """

    @abstractmethod
    async def read(self, path: str) -> Any:
        """Read a value from a workspace path."""
        pass

    @abstractmethod
    async def write(self, path: str, value: Any) -> None:
        """Write a value to a workspace path."""
        pass

    @abstractmethod
    async def list(self, pattern: str) -> list[str]:
        """List paths matching a pattern."""
        pass

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a value at a workspace path."""
        pass


class InMemoryWorkspace(WorkspaceInterface):
    """Simple in-memory workspace implementation for testing."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._listeners: list[Callable[[PathChanged], Any]] = []

    def add_listener(self, listener: Callable[[PathChanged], Any]) -> None:
        """Add a listener for path changes."""
        self._listeners.append(listener)

    async def read(self, path: str) -> Any:
        """Read a value from workspace."""
        return self._data.get(path)

    async def write(self, path: str, value: Any) -> None:
        """Write a value to workspace and notify listeners."""
        previous = self._data.get(path)
        self._data[path] = value

        # Notify listeners
        change = PathChanged(path=path, value=value, previous=previous)
        for listener in self._listeners:
            result = listener(change)
            if asyncio.iscoroutine(result):
                await result

    async def list(self, pattern: str) -> list[str]:
        """List paths matching a glob pattern."""
        return [p for p in self._data.keys() if fnmatch.fnmatch(p, pattern)]

    async def delete(self, path: str) -> None:
        """Delete a value at a path."""
        if path in self._data:
            previous = self._data.pop(path)
            change = PathChanged(path=path, value=None, previous=previous)
            for listener in self._listeners:
                result = listener(change)
                if asyncio.iscoroutine(result):
                    await result
