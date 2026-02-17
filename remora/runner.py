"""FunctionGemma runner implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Literal, Protocol

from remora.discovery import CSTNode
from remora.errors import AGENT_002
from remora.subagent import SubagentDefinition

try:
    from llama_cpp import Llama
except ImportError:  # pragma: no cover - optional dependency in tests

    class Llama:  # type: ignore[no-redef]
        def __init__(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("llama-cpp-python is required to load GGUF models.")


class CairnClient(Protocol):
    """Placeholder protocol for Cairn integration."""


class AgentError(RuntimeError):
    def __init__(
        self,
        *,
        node_id: str,
        operation: str,
        phase: Literal["init", "model_load", "loop", "tool", "merge"],
        error_code: str,
        message: str,
        traceback: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.node_id = node_id
        self.operation = operation
        self.phase = phase
        self.error_code = error_code
        self.message = message
        self.traceback = traceback
        self.timestamp = timestamp or datetime.now(timezone.utc)


class ModelCache:
    _instances: dict[str, Llama] = {}
    _lock = threading.Lock()

    @classmethod
    def get(cls, model_path: str, **kwargs: Any) -> Llama:
        with cls._lock:
            if model_path not in cls._instances:
                cls._instances[model_path] = Llama(model_path=model_path, **kwargs)
            return cls._instances[model_path]

    @classmethod
    def clear(cls) -> None:
        """For testing: clear all cached instances."""
        with cls._lock:
            cls._instances.clear()


@dataclass
class FunctionGemmaRunner:
    definition: SubagentDefinition
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient
    model: Llama = field(init=False)
    messages: list[dict[str, str]] = field(init=False)
    turn_count: int = field(init=False)

    def __post_init__(self) -> None:
        if not self.definition.model.exists():
            raise AgentError(
                node_id=self.node.node_id,
                operation=self.definition.name,
                phase="model_load",
                error_code=AGENT_002,
                message=f"GGUF not found: {self.definition.model}",
            )
        self.model = ModelCache.get(
            str(self.definition.model),
            n_ctx=4096,
            n_threads=2,
            verbose=False,
            n_gpu_layers=0,
        )
        self.messages = []
        self.turn_count = 0
        self._build_initial_messages()

    def _build_initial_messages(self) -> None:
        self.messages = [
            {
                "role": "system",
                "content": self.definition.initial_context.system_prompt,
            },
            {
                "role": "user",
                "content": self.definition.initial_context.render(self.node),
            },
        ]
