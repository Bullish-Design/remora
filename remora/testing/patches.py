from __future__ import annotations

from typing import Any

import pytest

from remora.testing.fakes import FakeAsyncOpenAI, FakeCompletionMessage


def patch_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: list[FakeCompletionMessage] | None = None,
    error: Exception | None = None,
) -> None:
    def _factory(*_: Any, **kwargs: Any) -> FakeAsyncOpenAI:
        return FakeAsyncOpenAI(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
            timeout=kwargs["timeout"],
            responses=list(responses or []),
            error=error,
        )

    monkeypatch.setattr("remora.runner.AsyncOpenAI", _factory)
