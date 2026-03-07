from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Trigger(BaseModel):
    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    agent_id: str
    correlation_id: str
    context: dict = Field(default_factory=dict)
    trigger_event: Any = None
