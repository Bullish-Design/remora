"""OpenAI-compatible client for vLLM and similar servers."""

from __future__ import annotations

import logging
from typing import Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from structured_agents.client.protocol import CompletionResponse
from structured_agents.exceptions import KernelError
from structured_agents.types import KernelConfig, TokenUsage

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """Client for OpenAI-compatible APIs (vLLM, etc.)."""

    def __init__(self, config: KernelConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
    ) -> CompletionResponse:
        """Make a chat completion request."""
        try:
            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice

            if extra_body:
                kwargs["extra_body"] = extra_body

            response = await self._client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            message = choice.message

            usage = None
            if response.usage:
                usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )

            tool_calls_raw = None
            if message.tool_calls:
                tool_calls_raw = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]

            return CompletionResponse(
                content=message.content,
                tool_calls=tool_calls_raw,
                usage=usage,
                finish_reason=choice.finish_reason,
                raw_response=response.model_dump(),
            )

        except APITimeoutError as exc:
            raise KernelError(
                f"LLM request timed out after {self._config.timeout}s: {exc}",
                phase="model_call",
            )
        except APIConnectionError as exc:
            raise KernelError(
                f"Failed to connect to LLM server at {self._config.base_url}: {exc}",
                phase="model_call",
            )
        except Exception as exc:
            raise KernelError(
                f"LLM request failed: {type(exc).__name__}: {exc}",
                phase="model_call",
            ) from exc

    async def close(self) -> None:
        """Close the client."""
        await self._client.close()
