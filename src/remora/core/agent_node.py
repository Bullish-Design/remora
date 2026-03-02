"""AgentNode unified model.

Single Pydantic model that serves as DB row, LLM prompt source,
and LSP protocol response. No subclasses. Specialization is data.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from remora.core.subscriptions import SubscriptionPattern


@dataclass
class ToolSchema:
    """Schema for an agent tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_llm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AgentNode(BaseModel):
    """Unified agent model: DB row, LLM prompt, and LSP response in one object.

    No subclasses. Specialization via data fields populated by extension configs.
    """

    model_config = ConfigDict(frozen=False)

    # --- Identity (from CSTNode via event projection) ---
    node_id: str
    node_type: str  # "function", "class", "method", "file", "section", "table"
    name: str
    full_name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str
    source_hash: str

    # --- Graph context (from edges table) ---
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # --- Runtime state (from event projections) ---
    status: str = "idle"  # "idle", "running", "error", "pending_approval"
    last_trigger_event: str = ""
    last_completed_at: float | None = None

    # --- Specialization (from extension config matching) ---
    extension_name: str | None = None
    custom_system_prompt: str = ""
    mounted_workspaces: list[str] = Field(default_factory=list)
    extra_tools: list[ToolSchema] = Field(default_factory=list)
    extra_subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
