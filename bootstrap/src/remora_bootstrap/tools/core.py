"""Core bootstrap tool set.

These tools are intentionally minimal and library-oriented.
"""

from __future__ import annotations

from remora_bootstrap.contracts import BootstrapTool


def _echo_tool(payload: dict) -> dict:
    return {"ok": True, "echo": payload.get("text", "")}


def _plan_stub_tool(payload: dict) -> dict:
    objective = str(payload.get("objective", "")).strip()
    if not objective:
        return {"ok": False, "error": "objective is required"}
    return {
        "ok": True,
        "plan": [
            f"Clarify objective: {objective}",
            "Identify target files and constraints",
            "Draft implementation steps",
        ],
    }


def default_tools() -> list[BootstrapTool]:
    return [
        BootstrapTool(
            name="echo",
            description="Return the submitted payload for bootstrap diagnostics",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_echo_tool,
        ),
        BootstrapTool(
            name="plan_stub",
            description="Create a basic plan skeleton for a stated objective",
            parameters={
                "type": "object",
                "properties": {"objective": {"type": "string"}},
                "required": ["objective"],
            },
            handler=_plan_stub_tool,
        ),
    ]
