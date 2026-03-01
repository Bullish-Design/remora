from typing import Any


class MockLLMClient:
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> Any:
        class MockResponse:
            tool_calls = []

        return MockResponse()
