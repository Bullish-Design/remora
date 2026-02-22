import argparse
import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

from structured_agents import (
    ContextProvider,
    FunctionGemmaPlugin,
    GrailBackend,
    GrailBackendConfig,
    KernelConfig,
    Message,
    ToolBackend,
    ToolCall,
    ToolResult,
    ToolSchema,
    build_client,
)
from structured_agents.grammar.config import GrammarConfig


JOB_DESCRIPTION_PATH = (
    Path(__file__).resolve().parent.parent
    / ".context"
    / "functiongemma_examples"
    / "distil-SHELLper-main"
    / "data"
    / "job_description.json"
)

TOOLS_DIR = Path("agents") / "shellper_demo"


def _clean_description(description: str) -> str:
    marker = "Tool description:"
    if marker in description:
        return description.split(marker, 1)[1].strip()
    return description.strip()


def load_shellper_tools() -> tuple[str, list[ToolSchema]]:
    data = json.loads(JOB_DESCRIPTION_PATH.read_text(encoding="utf-8"))
    tools: list[ToolSchema] = []
    for tool in data["tools"]:
        func = tool["function"]
        raw_description = func.get("description", "")
        tools.append(
            ToolSchema(
                name=func["name"],
                description=_clean_description(raw_description),
                parameters=func.get("parameters", {}),
                script_path=TOOLS_DIR / f"{func['name']}.pym",
            )
        )
    return data["task_description"], tools


def _default_value(prop: dict[str, Any]) -> object:
    if "default" in prop:
        return prop["default"]

    value_type = prop.get("type")
    if value_type == "boolean":
        return False
    if value_type == "integer":
        return 1
    if value_type == "number":
        return 1.0
    if value_type == "array":
        return []
    if value_type == "object":
        return {}
    return "sample.txt"


def build_default_arguments(schema: ToolSchema) -> dict[str, object]:
    params = schema.parameters
    properties = params.get("properties", {}) if isinstance(params, dict) else {}
    defaults: dict[str, object] = {}
    for name, prop in properties.items():
        if isinstance(prop, dict):
            defaults[name] = _default_value(prop)
        else:
            defaults[name] = "sample.txt"
    return defaults


class DefaultingBackend:
    def __init__(self, backend: GrailBackend) -> None:
        self._backend = backend

    async def execute(
        self, tool_call: ToolCall, tool_schema: ToolSchema, context: dict[str, Any]
    ) -> ToolResult:
        defaults = build_default_arguments(tool_schema)
        merged = {**defaults, **tool_call.arguments}
        updated_call = ToolCall(id=tool_call.id, name=tool_call.name, arguments=merged)
        return await self._backend.execute(updated_call, tool_schema, context)

    async def run_context_providers(
        self, providers: list[Path], context: dict[str, Any]
    ) -> list[str]:
        return await self._backend.run_context_providers(providers, context)

    def shutdown(self) -> None:
        self._backend.shutdown()


class ListToolSource:
    def __init__(self, tools: list[ToolSchema], backend: ToolBackend) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._backend = backend

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def resolve(self, tool_name: str) -> ToolSchema | None:
        return self._tools.get(tool_name)

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        return [self._tools[name] for name in tool_names if name in self._tools]

    async def execute(
        self, tool_call: ToolCall, tool_schema: ToolSchema, context: dict[str, Any]
    ) -> ToolResult:
        return await self._backend.execute(tool_call, tool_schema, context)

    def context_providers(self) -> list[ContextProvider]:
        return []


def select_prompts(count: int) -> list[str]:
    prompts = [
        "Show me what files are in my current directory please.",
        "What directory am I in right now?",
        "Create a folder called reports.",
        "Show me the last 5 lines of error_log.txt.",
        "Search for files with draft in the name.",
    ]
    if count <= len(prompts):
        return prompts[:count]
    cycle = itertools.cycle(prompts)
    return list(itertools.islice(cycle, count))


async def run_demo(
    calls: int, use_defaults: bool, log_requests: bool, log_responses: bool
) -> None:
    _task_description, tools = load_shellper_tools()

    config = KernelConfig(
        base_url="http://remora-server:8000/v1",
        model="google/functiongemma-270m-it",
        temperature=0,
        max_tokens=128,
        tool_choice="auto",
    )

    backend = GrailBackend(GrailBackendConfig(grail_dir=Path.cwd() / "agents"))
    backend_to_use = DefaultingBackend(backend) if use_defaults else backend
    tool_source = ListToolSource(tools, backend_to_use)
    plugin = FunctionGemmaPlugin()
    grammar_config = GrammarConfig()
    client = build_client(config)

    developer_prompt = (
        "You are a model that can do function calling with the following functions."
    )

    async def run_call(prompt: str) -> dict[str, object]:
        messages = [
            Message(role="developer", content=developer_prompt),
            Message(role="user", content=prompt),
        ]
        formatted_messages = plugin.format_messages(messages, tools)
        formatted_tools = plugin.format_tools(tools) if tools else None
        grammar = plugin.build_grammar(tools, grammar_config) if tools else None
        extra_body = plugin.to_extra_body(grammar)
        tool_choice = config.tool_choice if tools else "none"

        if log_requests:
            payload = {
                "model": config.model,
                "messages": formatted_messages,
                "tools": formatted_tools,
                "tool_choice": tool_choice,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "extra_body": extra_body,
            }
            print("\n--- Model Request ---")
            print(json.dumps({"prompt": prompt, "payload": payload}, indent=2))

        response = await client.chat_completion(
            messages=formatted_messages,
            tools=formatted_tools,
            tool_choice=tool_choice,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            extra_body=extra_body,
        )

        if log_responses:
            print("\n--- Model Response ---")
            print(
                json.dumps({"prompt": prompt, "raw": response.raw_response}, indent=2)
            )

        content, tool_calls = plugin.parse_response(
            response.content, response.tool_calls
        )
        if not tool_calls:
            return {
                "prompt": prompt,
                "error": "No tool call returned by the model.",
                "content": content,
            }

        tool_call = tool_calls[0]
        tool_schema = next(
            (tool for tool in tools if tool.name == tool_call.name), None
        )
        if not tool_schema:
            tool_result = ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"Unknown tool: {tool_call.name}",
                is_error=True,
            )
        else:
            tool_result = await tool_source.execute(tool_call, tool_schema, {})

        return {
            "prompt": prompt,
            "tool_call": {"name": tool_call.name, "arguments": tool_call.arguments},
            "tool_result": tool_result.output,
        }

    try:
        prompts = select_prompts(calls)
        results = await asyncio.gather(*(run_call(prompt) for prompt in prompts))
        for result in results:
            print("\n=== Demo Result ===")
            print(json.dumps(result, indent=2))
    finally:
        await client.close()
        if isinstance(backend_to_use, DefaultingBackend):
            backend_to_use.shutdown()
        else:
            backend.shutdown()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls", type=int, default=5)
    parser.add_argument("--no-defaults", action="store_true")
    parser.add_argument("--log-requests", action="store_true")
    parser.add_argument("--log-responses", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run_demo(
            args.calls,
            not args.no_defaults,
            args.log_requests,
            args.log_responses,
        )
    )


if __name__ == "__main__":
    main()
