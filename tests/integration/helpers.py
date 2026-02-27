from __future__ import annotations

import asyncio
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "vllm_server.yaml"
_AGENTFS_AVAILABLE: bool | None = None
_VLLM_AVAILABLE: dict[str, bool] = {}


def load_vllm_config() -> dict[str, str]:
    config: dict[str, str] = {
        "base_url": "http://remora-server:8000/v1",
        "api_key": "EMPTY",
        "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
    }

    if CONFIG_PATH.exists():
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        for key in ("base_url", "api_key", "model"):
            value = data.get(key)
            if value:
                config[key] = str(value)

    base_url = os.environ.get("REMORA_TEST_VLLM_BASE_URL")
    if base_url:
        config["base_url"] = base_url
    api_key = os.environ.get("REMORA_TEST_VLLM_API_KEY")
    if api_key:
        config["api_key"] = api_key
    model = os.environ.get("REMORA_TEST_VLLM_MODEL")
    if model:
        config["model"] = model

    return config


def vllm_available(base_url: str) -> bool:
    cached = _VLLM_AVAILABLE.get(base_url)
    if cached is not None:
        return cached
    url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            available = response.status == 200
    except Exception:
        available = False
    _VLLM_AVAILABLE[base_url] = available
    return available


async def agentfs_available(timeout: float = 3.0) -> bool:
    global _AGENTFS_AVAILABLE
    if _AGENTFS_AVAILABLE is not None:
        return _AGENTFS_AVAILABLE
    try:
        from fsdantic import Fsdantic
    except Exception:
        _AGENTFS_AVAILABLE = False
        return _AGENTFS_AVAILABLE

    temp_dir = Path(tempfile.mkdtemp(prefix="remora-agentfs-"))
    db_path = temp_dir / "agentfs.db"

    try:
        workspace = await asyncio.wait_for(Fsdantic.open(path=str(db_path)), timeout=timeout)
    except Exception:
        _AGENTFS_AVAILABLE = False
        return _AGENTFS_AVAILABLE

    try:
        await asyncio.wait_for(workspace.close(), timeout=timeout)
    except Exception:
        _AGENTFS_AVAILABLE = False
        return _AGENTFS_AVAILABLE

    _AGENTFS_AVAILABLE = True
    return _AGENTFS_AVAILABLE


def agentfs_available_sync(timeout: float = 3.0) -> bool:
    try:
        return asyncio.run(agentfs_available(timeout=timeout))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(agentfs_available(timeout=timeout))
        finally:
            loop.close()


def write_bundle(
    bundle_dir: Path,
    *,
    name: str = "smoke_agent",
    system_prompt: str = "You are a minimal smoke-test agent. Provide a short response.",
    max_turns: int = 2,
) -> Path:
    prompt_block = _indent_block(system_prompt, 4)
    tools_dir = bundle_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "bundle.yaml"
    bundle_path.write_text(
        (
            "\n".join(
                [
                    f"name: {name}",
                    "model: qwen",
                    "initial_context:",
                    "  system_prompt: |",
                    prompt_block,
                    "agents_dir: tools",
                    f"max_turns: {max_turns}",
                ]
            )
            + "\n"
        ),
        encoding="utf-8",
    )
    return bundle_path


def write_tool_bundle(
    bundle_dir: Path,
    *,
    tools: dict[str, str],
    name: str = "tool_agent",
    system_prompt: str = "You are a tool-calling test agent.",
    max_turns: int = 3,
    include_grammar: bool = True,
) -> Path:
    tools_dir = bundle_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for tool_name, body in tools.items():
        tool_path = tools_dir / f"{tool_name}.pym"
        tool_path.write_text(body, encoding="utf-8")

    prompt_block = _indent_block(system_prompt, 4)
    lines = [
        f"name: {name}",
        "model: qwen",
        "initial_context:",
        "  system_prompt: |",
        prompt_block,
    ]
    if include_grammar:
        lines.extend(
            [
                "grammar:",
                "  strategy: ebnf",
                "  allow_parallel_calls: false",
                "  send_tools_to_api: false",
            ]
        )
    lines.extend(["agents_dir: tools", f"max_turns: {max_turns}"])

    bundle_path = bundle_dir / "bundle.yaml"
    bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle_path


def _indent_block(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def write_config(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
