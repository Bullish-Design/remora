import asyncio
import importlib
from pathlib import Path
from typing import Any

from demo.core import (
    ASTAgentNode,
    RewriteProposal,
    AgentEvent,
    HumanChatEvent,
    AgentMessageEvent,
    RewriteProposalEvent,
    AgentErrorEvent,
    generate_id,
)
from demo.lsp.server import server, publish_diagnostics, emit_event


MAX_CHAIN_DEPTH = 10


class Trigger:
    def __init__(self, agent_id: str, correlation_id: str, context: dict = None):
        self.agent_id = agent_id
        self.correlation_id = correlation_id
        self.context = context or {}


class MockLLMClient:
    async def chat(self, messages, tools=None):
        class MockResponse:
            tool_calls = []

        return MockResponse()


class AgentRunner:
    def __init__(self):
        self.server = server
        self.llm = MockLLMClient()
        self.queue = asyncio.Queue()
        self._running = False

    async def run_forever(self):
        self._running = True
        while self._running:
            trigger = await self.queue.get()
            await self.execute_turn(trigger)

    def stop(self):
        self._running = False

    async def trigger(self, agent_id: str, correlation_id: str, context: dict = None):
        chain = self.server.db.get_activation_chain(correlation_id)

        if len(chain) >= MAX_CHAIN_DEPTH:
            await self.emit_error(agent_id, "Max activation depth exceeded", correlation_id)
            return

        if agent_id in [e.agent_id for e in chain]:
            await self.emit_error(agent_id, "Cycle detected in activation chain", correlation_id)
            return

        await self.queue.put(Trigger(agent_id=agent_id, correlation_id=correlation_id, context=context or {}))

    async def emit_error(self, agent_id: str, error: str, correlation_id: str):
        await emit_event(AgentErrorEvent(agent_id=agent_id, error=error, correlation_id=correlation_id))

    async def execute_turn(self, trigger: Trigger):
        agent_id = trigger.agent_id
        correlation_id = trigger.correlation_id

        self.server.db.set_status(agent_id, "running")
        await self.refresh_code_lens(agent_id)

        self.server.db.add_to_chain(correlation_id, agent_id)

        node = self.server.db.get_node(agent_id)
        if not node:
            await self.emit_error(agent_id, "Node not found", correlation_id)
            return

        agent = ASTAgentNode(**node)
        agent = self.apply_extensions(agent)

        messages = [
            {"role": "system", "content": agent.to_system_prompt()},
        ]

        events = self.server.db.get_events_for_correlation(correlation_id)
        for event in events:
            if isinstance(event, HumanChatEvent) and event.to_agent == agent_id:
                messages.append({"role": "user", "content": event.message})
            elif isinstance(event, AgentMessageEvent) and event.to_agent == agent_id:
                messages.append({"role": "user", "content": f"[From {event.from_agent}]: {event.message}"})

        if trigger.context.get("rejection_feedback"):
            messages.append(
                {"role": "user", "content": f"[Feedback on rejected proposal]: {trigger.context['rejection_feedback']}"}
            )

        tools = self.get_agent_tools(agent)

        try:
            response = await self.llm.chat(messages, tools)
            await self.handle_response(agent, response, correlation_id)
        except Exception as e:
            await self.emit_error(agent_id, str(e), correlation_id)
        finally:
            self.server.db.set_status(agent_id, "active")
            await self.refresh_code_lens(agent_id)

    async def handle_response(self, agent: ASTAgentNode, response, correlation_id: str):
        for tool_call in response.tool_calls:
            tool_name = getattr(tool_call, "name", None) or getattr(tool_call, "function", {}).get("name", "")
            args = getattr(tool_call, "arguments", {}) or getattr(tool_call, "function", {}).get("arguments", {})

            match tool_name:
                case "rewrite_self":
                    new_source = args.get("new_source", "")
                    await self.create_proposal(agent, new_source, correlation_id)

                case "message_node":
                    target_id = args.get("target_id", "")
                    message = args.get("message", "")
                    await self.message_node(agent.remora_id, target_id, message, correlation_id)

                case "read_node":
                    target_id = args.get("target_id", "")
                    target = self.server.db.get_node(target_id)

                case _:
                    await self.execute_extension_tool(agent, tool_name, args, correlation_id)

    async def create_proposal(self, agent: ASTAgentNode, new_source: str, correlation_id: str):
        proposal_id = generate_id()
        proposal = RewriteProposal(
            proposal_id=proposal_id,
            agent_id=agent.remora_id,
            file_path=agent.file_path,
            old_source=agent.source_code,
            new_source=new_source,
            start_line=agent.start_line,
            end_line=agent.end_line,
            correlation_id=correlation_id,
        )

        self.server.proposals[proposal_id] = proposal
        self.server.db.set_pending_proposal(agent.remora_id, proposal_id)
        self.server.db.set_status(agent.remora_id, "pending_approval")
        self.server.db.store_proposal(proposal_id, agent.remora_id, agent.source_code, new_source, proposal.diff)

        await publish_diagnostics(agent.file_path, [proposal])

        await self.refresh_code_lens(agent.remora_id)

        await emit_event(
            RewriteProposalEvent(
                agent_id=agent.remora_id, proposal_id=proposal_id, diff=proposal.diff, correlation_id=correlation_id
            )
        )

    async def message_node(self, from_id: str, to_id: str, message: str, correlation_id: str):
        await emit_event(
            AgentMessageEvent(from_agent=from_id, to_agent=to_id, message=message, correlation_id=correlation_id)
        )

        await self.trigger(to_id, correlation_id)

    async def refresh_code_lens(self, agent_id: str):
        node = self.server.db.get_node(agent_id)
        if node:
            agent = ASTAgentNode(**node)
            await publish_code_lenses(node["file_path"], [agent])

    def get_agent_tools(self, agent: ASTAgentNode) -> list[dict]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "rewrite_self",
                    "description": "Rewrite the agent's own source code with new implementation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_source": {
                                "type": "string",
                                "description": "The new source code for this function/class",
                            }
                        },
                        "required": ["new_source"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "message_node",
                    "description": "Send a message to another agent to request changes",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_id": {"type": "string", "description": "The remora_id of the target agent"},
                            "message": {"type": "string", "description": "Message to send to the target agent"},
                        },
                        "required": ["target_id", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_node",
                    "description": "Read another agent's source code",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_id": {"type": "string", "description": "The remora_id of the target agent"}
                        },
                        "required": ["target_id"],
                    },
                },
            },
        ]

        for tool in agent.extra_tools:
            tools.append(tool.to_llm_tool())

        return tools

    def apply_extensions(self, agent: ASTAgentNode) -> ASTAgentNode:
        extensions = load_extensions_from_disk()

        for ext_cls in extensions:
            if ext_cls.matches(agent.node_type, agent.name):
                ext = ext_cls()
                agent.custom_system_prompt = ext.system_prompt
                agent.mounted_workspaces = ext.get_workspaces()
                agent.extra_tools = ext.get_tool_schemas()
                break

        return agent

    async def execute_extension_tool(self, agent: ASTAgentNode, tool_name: str, params: dict, correlation_id: str):
        pass


def load_extensions_from_disk():
    extensions = []
    models_dir = Path(".remora/models")

    if not models_dir.exists():
        return extensions

    for py_file in models_dir.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                for name, obj in module.__dict__.items():
                    if isinstance(obj, type) and issubclass(obj, ExtensionNode) and obj is not ExtensionNode:
                        extensions.append(obj)
        except Exception:
            pass

    return extensions


class ExtensionNode:
    @classmethod
    def matches(cls, node_type: str, name: str) -> bool:
        return False

    @property
    def system_prompt(self) -> str:
        return ""

    def get_workspaces(self) -> str:
        return ""

    def get_tool_schemas(self) -> list:
        return []


async def publish_code_lenses(uri: str, nodes: list[ASTAgentNode]):
    from demo.lsp.server import server, publish_code_lenses as _publish

    await _publish(uri, nodes)
