"""Mock vLLM server for testing without real inference."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

from remora.constants import TERMINATION_TOOL


@dataclass
class MockResponse:
    """Represents a canned response for the mock server."""

    pattern: str
    response: dict[str, Any]


@dataclass
class MockVLLMServer:
    """A mock vLLM server that returns canned responses."""

    host: str = "127.0.0.1"
    port: int = 8765
    responses: list[MockResponse] = field(default_factory=list)
    default_model: str = "google/functiongemma-270m-it"
    _app: web.Application | None = None
    _runner: web.AppRunner | None = None

    def add_response(self, pattern: str, response: dict[str, Any]) -> None:
        """Add a canned response for prompts matching the pattern."""
        self.responses.append(MockResponse(pattern=pattern, response=response))

    def add_tool_call_response(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        pattern: str = ".*",
    ) -> None:
        """Add a response that calls a specific tool."""
        response = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 1234567890,
            "model": self.default_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_mock",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        self.add_response(pattern, response)

    async def _handle_models(self, request: web.Request) -> web.Response:
        """Handle GET /v1/models."""
        return web.json_response(
            {
                "object": "list",
                "data": [{"id": self.default_model, "object": "model"}],
            }
        )

    async def _handle_completions(self, request: web.Request) -> web.Response:
        """Handle POST /v1/chat/completions."""
        import re

        body = await request.json()
        messages = body.get("messages", [])

        user_content = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user_content = message.get("content", "")
                break

        for index, mock_response in enumerate(self.responses):
            if re.search(mock_response.pattern, user_content, re.IGNORECASE):
                self.responses.pop(index)
                return web.json_response(mock_response.response)

        return web.json_response(
            {
                "id": "chatcmpl-default",
                "object": "chat.completion",
                "created": 1234567890,
                "model": self.default_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_default",
                                    "type": "function",
                                    "function": {
                                        "name": TERMINATION_TOOL,
                                        "arguments": json.dumps(
                                            {
                                                "summary": "Mock completion",
                                                "changed_files": [],
                                                "details": {},
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )

    async def start(self) -> str:
        """Start the mock server and return its URL."""
        self._app = web.Application()
        self._app.router.add_get("/v1/models", self._handle_models)
        self._app.router.add_post("/v1/chat/completions", self._handle_completions)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        return f"http://{self.host}:{self.port}/v1"

    async def stop(self) -> None:
        """Stop the mock server."""
        if self._runner:
            await self._runner.cleanup()
