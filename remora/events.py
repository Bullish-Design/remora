"""Event stream helpers for Remora."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import asyncio
from typing import Any, Protocol, TextIO

from remora.config import EventStreamConfig


ENV_EVENT_STREAM = "REMORA_EVENT_STREAM"
ENV_EVENT_STREAM_FILE = "REMORA_EVENT_STREAM_FILE"


class EventEmitter(Protocol):
    enabled: bool
    include_payloads: bool
    max_payload_chars: int

    def emit(self, payload: dict[str, Any]) -> None: ...

    def close(self) -> None: ...


@dataclass
class NullEventEmitter:
    enabled: bool = False
    include_payloads: bool = False
    max_payload_chars: int = 0

    def emit(self, payload: dict[str, Any]) -> None:
        return

    def close(self) -> None:
        return


@dataclass
class CompositeEventEmitter:
    """Fans out events to multiple emitters."""
    emitters: list[EventEmitter]
    enabled: bool = True
    include_payloads: bool = True
    max_payload_chars: int = 4000

    def emit(self, payload: dict[str, Any]) -> None:
        for emitter in self.emitters:
            emitter.emit(payload)

    def close(self) -> None:
        for emitter in self.emitters:
            emitter.close()


@dataclass
class JsonlEventEmitter:
    stream: TextIO
    enabled: bool = True
    include_payloads: bool = True
    max_payload_chars: int = 4000

    def emit(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        out = {**payload}
        out.setdefault("ts", _iso_timestamp())
        try:
            message = json.dumps(out, default=str)
        except (TypeError, ValueError):
            fallback = {"event": "event_encode_error", "payload": str(payload)}
            message = json.dumps(fallback)
        try:
            self.stream.write(f"{message}\n")
            self.stream.flush()
        except OSError:
            return

    def close(self) -> None:
        if self.stream in (sys.stdout, sys.stderr):
            return
        try:
            self.stream.close()
        except OSError:
            return


@dataclass
class EventStreamController:
    config: EventStreamConfig
    enabled: bool = False
    output: Path | None = None
    include_payloads: bool = True
    max_payload_chars: int = 4000
    _emitter: EventEmitter = field(init=False, default_factory=NullEventEmitter)
    _last_mtime: float | None = None

    def __post_init__(self) -> None:
        self.enabled = self.config.enabled
        self.output = self.config.output
        self.include_payloads = self.config.include_payloads
        self.max_payload_chars = self.config.max_payload_chars
        self._emitter = self._build_emitter(self.enabled, self.output)

    def emit(self, payload: dict[str, Any]) -> None:
        self._emitter.emit(payload)

    def close(self) -> None:
        self._emitter.close()

    async def watch(self, poll_interval: float = 0.5) -> None:
        control_file = self.config.control_file
        if control_file is None:
            return
        while True:
            await asyncio.sleep(poll_interval)
            if not control_file.exists():
                continue
            try:
                mtime = control_file.stat().st_mtime
            except OSError:
                continue
            if self._last_mtime is not None and mtime <= self._last_mtime:
                continue
            self._last_mtime = mtime
            payload = self._read_control_file(control_file)
            if payload is None:
                continue
            enabled = payload.get("enabled")
            if not isinstance(enabled, bool):
                continue
            output_value = payload.get("output")
            output_path = Path(output_value) if isinstance(output_value, str) and output_value else None
            if enabled and output_path is None:
                output_path = self.config.output
            self._apply_state(enabled, output_path)

    def _apply_state(self, enabled: bool, output: Path | None) -> None:
        if enabled == self.enabled and output == self.output:
            return
        self._emitter.close()
        self.enabled = enabled
        self.output = output
        self._emitter = self._build_emitter(enabled, output)

    @staticmethod
    def _read_control_file(path: Path) -> dict[str, Any] | None:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _build_emitter(self, enabled: bool, output: Path | None) -> EventEmitter:
        if not enabled:
            return NullEventEmitter(
                include_payloads=self.include_payloads,
                max_payload_chars=self.max_payload_chars,
            )
        if output is None:
            return JsonlEventEmitter(
                stream=sys.stdout,
                include_payloads=self.include_payloads,
                max_payload_chars=self.max_payload_chars,
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        stream = output.open("a", encoding="utf-8")
        return JsonlEventEmitter(
            stream=stream,
            include_payloads=self.include_payloads,
            max_payload_chars=self.max_payload_chars,
        )


def resolve_event_stream_config(
    config: EventStreamConfig,
    *,
    enabled_override: bool | None = None,
    output_override: Path | None = None,
) -> EventStreamConfig:
    enabled = _resolve_enabled(config.enabled, enabled_override)
    output = _resolve_output(config.output, output_override)
    return EventStreamConfig(
        enabled=enabled,
        output=output,
        control_file=config.control_file,
        include_payloads=config.include_payloads,
        max_payload_chars=config.max_payload_chars,
    )


def build_event_emitter(
    config: EventStreamConfig,
    *,
    enabled_override: bool | None = None,
    output_override: Path | None = None,
) -> EventStreamController:
    resolved = resolve_event_stream_config(
        config,
        enabled_override=enabled_override,
        output_override=output_override,
    )
    return EventStreamController(resolved)


def _resolve_enabled(default: bool, override: bool | None) -> bool:
    if override is not None:
        return override
    env_value = _parse_env_bool(ENV_EVENT_STREAM)
    if env_value is not None:
        return env_value
    return default


def _resolve_output(default: Path | None, override: Path | None) -> Path | None:
    if override is not None:
        return override
    env_value = os.getenv(ENV_EVENT_STREAM_FILE)
    if env_value:
        return Path(env_value)
    return default


def _parse_env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
