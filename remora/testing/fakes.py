from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any


class FakeToolCallFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, *, name: str, arguments: str, call_id: str = "call-1") -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeToolCallFunction(name, arguments)


class FakeCompletionMessage:
    def __init__(self, *, content: str | None = None, tool_calls: list[FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, Any]:
        tool_calls = None
        if self.tool_calls is not None:
            tool_calls = [
                {
                    "id": call.id,
                    "type": call.type,
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in self.tool_calls
            ]
        data: dict[str, Any] = {"role": "assistant", "content": self.content, "tool_calls": tool_calls}
        if exclude_none:
            return {key: value for key, value in data.items() if value is not None}
        return data


class FakeCompletionChoice:
    def __init__(self, message: FakeCompletionMessage) -> None:
        self.message = message


class FakeCompletionResponse:
    def __init__(self, message: FakeCompletionMessage) -> None:
        self.choices = [FakeCompletionChoice(message)]


class FakeChatCompletions:
    def __init__(self, responses: list[FakeCompletionMessage], *, error: Exception | None = None) -> None:
        self.responses = responses
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        max_tokens: int,
        temperature: float,
    ) -> FakeCompletionResponse:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if self.error:
            raise self.error
        if not self.responses:
            raise AssertionError("No responses queued for FakeChatCompletions")
        return FakeCompletionResponse(self.responses.pop(0))


class FakeAsyncOpenAI:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: int,
        responses: list[FakeCompletionMessage] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=FakeChatCompletions(responses or [], error=error))


class FakeGrailExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def execute(
        self,
        pym_path: Path,
        grail_dir: Path,
        inputs: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append((pym_path, inputs))
        if pym_path.name == "inspect.pym":
            return {"result": {"ok": True}}
        if pym_path.name == "ctx-1.pym":
            return {"result": {"ctx": "one"}}
        if pym_path.name == "ctx-2.pym":
            return {"result": {"ctx": "two"}}
        return {"result": {}}
