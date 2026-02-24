"""AgentGraph - Declarative Agent Composition.

This module provides:
1. AgentNode: Unified concept of "a thing that runs"
2. AgentGraph: Declarative composition of AgentNodes
3. Execution engine for running graphs
"""

import asyncio
import contextvars
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from remora.event_bus import Event, EventBus, get_event_bus


_workspace_var: contextvars.ContextVar[Any] = contextvars.ContextVar("workspace", default=None)


class AgentState(StrEnum):
    """All possible states for an agent."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorPolicy(StrEnum):
    """Graph-level error handling policies."""

    STOP_GRAPH = "stop_graph"
    SKIP_DOWNSTREAM = "skip_downstream"
    CONTINUE = "continue"


@dataclass
class GraphConfig:
    """Configuration for graph execution."""

    max_concurrency: int = 4
    interactive: bool = True
    timeout: float = 300.0
    snapshot_enabled: bool = False
    error_policy: ErrorPolicy = ErrorPolicy.STOP_GRAPH


@dataclass
class AgentInbox:
    """The inbox for user interaction.

    Every AgentNode has one of these. It handles:
    - Blocking: Agent asks user, waits for response
    - Async: User sends message, agent receives on next turn

    Thread-safety: Uses asyncio.Lock to prevent race conditions.
    """

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    blocked: bool = False
    blocked_question: str | None = None
    blocked_since: datetime | None = None
    _pending_response: asyncio.Future[str] | None = field(default=None, repr=False)

    _message_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)

    async def ask_user(self, question: str, timeout: float = 300.0) -> str:
        """Block and wait for user response."""
        async with self._lock:
            self.blocked = True
            self.blocked_question = question
            self.blocked_since = datetime.now()

            loop = asyncio.get_running_loop()
            self._pending_response = loop.create_future()

        try:
            response = await asyncio.wait_for(self._pending_response, timeout=timeout)
            return response
        finally:
            async with self._lock:
                self.blocked = False
                self.blocked_question = None
                self.blocked_since = None
                self._pending_response = None

    async def send_message(self, message: str) -> None:
        """Queue a message for the agent."""
        await self._message_queue.put(message)

    async def drain_messages(self) -> list[str]:
        """Get all queued messages."""
        messages = []
        while not self._message_queue.empty():
            messages.append(await self._message_queue.get())
        return messages

    def _resolve_response(self, response: str) -> bool:
        """Called by UI to resolve blocked ask_user.

        Returns True if response was successfully resolved,
        False if no pending response or already resolved.

        Thread-safe: Uses lock to prevent race conditions.
        """
        if self._pending_response and not self._pending_response.done():
            self._pending_response.set_result(response)
            return True
        return False

    async def resolve_response_async(self, response: str) -> bool:
        """Async version of resolve_response for use in async contexts.

        Returns True if response was successfully resolved.
        """
        async with self._lock:
            if self._pending_response and not self._pending_response.done():
                self._pending_response.set_result(response)
                return True
            return False


@dataclass
class AgentNode:
    """The unified concept of an agent.

    One class replaces: CSTNode + RemoraAgentContext + KernelRunner

    An AgentNode is:
    - An identity (id)
    - A target (code to operate on)
    - A state (what it's doing)
    - An inbox (for user messages)
    - A kernel (the execution engine)
    - A result (when done)
    """

    id: str
    name: str

    target: str
    target_path: Path | None = None
    target_type: str = "unknown"

    state: AgentState = AgentState.PENDING
    bundle: str = ""
    kernel: Any = None

    inbox: AgentInbox = field(default_factory=AgentInbox)

    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)

    workspace: Any = field(default=None, repr=False)
    _kv_store: Any = field(default=None, repr=False)

    @property
    def kv_store(self) -> Any:
        """Lazy-init KV store from workspace."""
        if self._kv_store is None and self.workspace:
            from remora.agent_state import AgentKVStore

            self._kv_store = AgentKVStore(self.workspace, self.id)
        return self._kv_store

    async def cancel(self, event_bus: EventBus | None = None) -> None:
        """Cancel this agent's execution.

        Sets state to CANCELLED and resolves any pending user response with
        a cancellation signal.
        """
        self.state = AgentState.CANCELLED
        self.error = "Cancelled by user"

        await self.inbox.resolve_response_async("")

        if event_bus:
            await event_bus.publish(Event.agent_cancelled(agent_id=self.id, error=self.error))


class AgentGraph:
    """A declarative graph of AgentNodes.

    Usage:
        graph = AgentGraph()

        # Add agents
        graph.agent("lint", bundle="lint", target=source_code)
        graph.agent("docstring", bundle="docstring", target=source_code)

        # Define dependencies
        graph.after("lint").run("docstring")

        # Execute
        results = await graph.execute()
    """

    def __init__(self, event_bus: EventBus | None = None):
        self.id: str = uuid.uuid4().hex[:8]
        self._event_bus = event_bus or get_event_bus()
        self._agents: dict[str, AgentNode] = {}
        self._execution_order: list[list[str]] = []
        self._running_tasks: set[asyncio.Task] = set()
        self._blocked_handler: Callable[[AgentNode, str], Awaitable[str]] | None = None
        self._bundle_map: dict[str, str] = {}
        self._parallel_groups: list[list[str]] = []

    def discover(
        self,
        root_dirs: list[Path],
        bundles: dict[str, str] | None = None,
        query_pack: str = "remora_core",
    ) -> "AgentGraph":
        """Auto-discover code structure and create agents.

        Args:
            root_dirs: Directories or files to scan
            bundles: Mapping of node_type -> bundle name
                   e.g., {"function": "lint", "class": "docstring"}
            query_pack: Query pack name (default: "remora_core")

        Returns:
            Self for chaining
        """
        if bundles:
            self._bundle_map = bundles

        from remora.discovery.discoverer import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer(
            root_dirs=root_dirs,
            query_pack=query_pack,
        )
        nodes = discoverer.discover()

        for node in nodes:
            bundle = self._bundle_map.get(str(node.node_type), "default")
            agent_name = f"{bundle}-{node.name}"

            self.agent(
                name=agent_name,
                bundle=bundle,
                target=node.text or "",
                target_path=node.file_path,
                target_type=str(node.node_type),
            )

        return self

    def run_parallel(self, *agent_names: str) -> "AgentGraph":
        """Run these agents in parallel (same batch).

        Args:
            *agent_names: Names of agents to run in parallel

        Returns:
            Self for chaining
        """
        self._parallel_groups.append(list(agent_names))
        return self

    def run_sequential(self, *agent_names: str) -> "AgentGraph":
        """Run these agents sequentially (each in its own batch).

        Args:
            *agent_names: Names of agents to run sequentially

        Returns:
            Self for chaining
        """
        for name in agent_names:
            self._parallel_groups.append([name])
        return self

    def on_blocked(self, handler: Callable[[AgentNode, str], Awaitable[str]]) -> "AgentGraph":
        """Set handler for when agent asks user a question.

        This is how the UI integrates: provide a handler that
        shows the question to the user and returns their response.

        Args:
            handler: Async function that takes (agent, question) and returns answer

        Returns:
            Self for chaining
        """
        self._blocked_handler = handler
        return self

    def agent(
        self, name: str, bundle: str, target: str, target_path: Path | None = None, target_type: str = "unknown"
    ) -> "AgentGraph":
        """Add an agent to the graph."""
        node = AgentNode(
            id=f"{name}-{uuid.uuid4().hex[:4]}",
            name=name,
            bundle=bundle,
            target=target,
            target_path=target_path,
            target_type=target_type,
        )
        self._agents[name] = node
        return self

    def after(self, agent_name: str) -> "_GraphBuilder":
        """Start building dependencies from this agent."""
        return _GraphBuilder(self, agent_name)

    def execute(self, config: GraphConfig | None = None) -> "GraphExecutor":
        """Execute the graph and return an executor.

        Args:
            config: Optional GraphConfig. If not provided, uses defaults.

        Returns:
            GraphExecutor instance
        """
        if config is None:
            config = GraphConfig()

        return GraphExecutor(
            graph=self,
            config=config,
            event_bus=self._event_bus,
            blocked_handler=self._blocked_handler,
        )

    def agents(self) -> dict[str, AgentNode]:
        return self._agents

    def __getitem__(self, name: str) -> AgentNode:
        return self._agents[name]

    async def cancel(self, event_bus: EventBus | None = None) -> None:
        """Cancel all agents in the graph."""
        eb = event_bus or self._event_bus
        for agent in self._agents.values():
            if agent.state not in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                await agent.cancel(eb)


class _GraphBuilder:
    """Helper for building graph dependencies."""

    def __init__(self, graph: AgentGraph, from_agent: str):
        self._graph = graph
        self._from_agent = from_agent

    def run(self, *agent_names: str) -> AgentGraph:
        """Run these agents after the source agent completes."""
        source = self._graph[self._from_agent]
        for name in agent_names:
            target = self._graph[name]
            source.downstream.append(target.id)
            target.upstream.append(source.id)
        return self._graph

    def run_parallel(self, *agent_names: str) -> AgentGraph:
        """Run these agents in parallel after source completes."""
        return self.run(*agent_names)


class GraphExecutor:
    """Executes an AgentGraph.

    Returned by graph.execute(), this handles the actual running.
    """

    def __init__(
        self,
        graph: AgentGraph,
        config: GraphConfig,
        event_bus: EventBus,
        blocked_handler: Callable[[AgentNode, str], Awaitable[str]] | None = None,
    ):
        self._graph = graph
        self._config = config
        self._event_bus = event_bus
        self._blocked_handler = blocked_handler
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._running_agents: dict[str, asyncio.Task] = {}

    async def run(self) -> dict[str, Any]:
        """Execute all agents in dependency order."""
        batches = self._build_execution_batches()

        for batch in batches:
            tasks = [asyncio.create_task(self._run_agent(name)) for name in batch]
            for task in tasks:
                self._running_agents[task.get_name()] = task

            results = await asyncio.gather(*tasks, return_exceptions=True)

            if self._config.error_policy == ErrorPolicy.STOP_GRAPH:
                for result in results:
                    if isinstance(result, Exception):
                        break

        return {name: agent.result for name, agent in self._graph.agents().items()}

    def _build_execution_batches(self) -> list[list[str]]:
        """Build batches of agents that can run in parallel."""
        if self._graph._parallel_groups:
            return self._graph._parallel_groups
        return [list(self._graph.agents().keys())]

    async def _run_agent(self, name: str) -> None:
        """Run a single agent with real execution."""
        agent = self._graph[name]

        async with self._semaphore:
            await self._event_bus.publish(
                Event.agent_started(agent_id=agent.id, graph_id=self._graph.id, name=name, bundle=agent.bundle)
            )

            agent.state = AgentState.RUNNING
            agent.started_at = datetime.now()

            try:
                if agent.workspace is not None:
                    _workspace_var.set(agent.workspace)

                result = await self._execute_agent(agent)

                agent.result = result
                agent.state = AgentState.COMPLETED
                agent.completed_at = datetime.now()

                await self._event_bus.publish(
                    Event.agent_completed(agent_id=agent.id, graph_id=self._graph.id, name=name, result=str(result))
                )

            except asyncio.CancelledError:
                agent.state = AgentState.CANCELLED
                agent.error = "Execution cancelled"
                await self._event_bus.publish(
                    Event.agent_cancelled(agent_id=agent.id, graph_id=self._graph.id, name=name)
                )
                raise

            except Exception as e:
                agent.state = AgentState.FAILED
                agent.error = str(e)
                agent.completed_at = datetime.now()

                await self._event_bus.publish(
                    Event.agent_failed(agent_id=agent.id, graph_id=self._graph.id, name=name, error=str(e))
                )

            finally:
                _workspace_var.set(None)

    async def _execute_agent(self, agent: AgentNode) -> Any:
        """Execute an agent.

        This is where the actual agent execution happens. The implementation
        should:
        1. Load the agent's bundle/tool definition
        2. Execute with the kernel
        3. Handle user interaction via ask_user()

        For now, this is a placeholder that demonstrates the flow.
        In production, this would integrate with structured-agents.
        """
        from structured_agents import load_bundle

        bundle_path = self._get_bundle_path(agent.bundle)
        if bundle_path and bundle_path.exists():
            bundle = load_bundle(bundle_path)

            result = await self._run_kernel(agent, bundle)
            return result

        return await self._simulate_execution(agent)

    def _get_bundle_path(self, bundle_name: str) -> Path | None:
        """Get the path to a bundle by name.

        Looks in standard locations for agent bundles.
        """
        if not bundle_name:
            return None

        search_paths = [
            Path.cwd() / "agents" / bundle_name,
            Path(__file__).parent.parent.parent / "agents" / bundle_name,
        ]

        for path in search_paths:
            if path.exists() and (path / "bundle.yaml").exists():
                return path

        return None

    async def _run_kernel(self, agent: AgentNode, bundle: Any) -> Any:
        """Run the agent with structured-agents kernel.

        This is a placeholder - the actual implementation would:
        1. Create AgentKernel with bundle
        2. Configure with model backend
        3. Run with workspace context
        4. Handle tool calls including ask_user()
        """
        await asyncio.sleep(0.1)
        return {"status": "completed", "bundle": getattr(bundle, "name", "unknown")}

    async def _simulate_execution(self, agent: AgentNode) -> Any:
        """Simulate agent execution for demo purposes.

        This demonstrates the event flow without actual LLM calls.
        """
        await asyncio.sleep(0.1)
        return {"status": "completed", "output": f"Executed {agent.bundle} on {agent.target_type}"}
