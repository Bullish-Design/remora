"""Human-readable LLM conversation logger."""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)


class LlmConversationLogger:
    """Writes human-readable LLM conversation transcripts.
    
    Hooks into the existing EventEmitter system and reformats
    structured events into readable conversation logs.
    """

    def __init__(
        self,
        output: Path | TextIO | None = None,
        *,
        include_full_prompts: bool = False,
        max_content_lines: int = 100,
    ) -> None:
        self._output = output
        self._include_full_prompts = include_full_prompts
        self._max_content_lines = max_content_lines
        self._stream: TextIO | None = None
        self._current_agent: str | None = None
        # buffer for atomic turn logging: agent_id -> request_payload
        self._pending_requests: dict[str, dict] = {}
    
    def open(self) -> None:
        output = self._output
        if isinstance(output, Path):
            # Generate timestamped filename for daily rotation
            date_str = datetime.now().strftime("%Y-%m-%d")
            
            if output.is_dir():
                log_file = output / f"llm_conversations_{date_str}.log"
            else:
                stem = output.stem
                suffix = output.suffix
                log_file = output.with_name(f"{stem}_{date_str}{suffix}")
            
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._stream = log_file.open("a", encoding="utf-8")
        elif hasattr(output, "write"):
            self._stream = output
    
    def close(self) -> None:
        if self._stream and isinstance(self._output, Path):
            self._stream.close()
    
    def emit(self, payload: dict[str, Any]) -> None:
        """Route an event payload to the appropriate formatter."""
        event = payload.get("event", "")
        handler = getattr(self, f"_handle_{event}", None)
        if handler:
            handler(payload)
    
    def _write(self, text: str) -> None:
        if self._stream:
            self._stream.write(text + "\n")
            self._stream.flush()
    
    def _handle_model_request(self, p: dict) -> None:
        # Buffer the request; do not print yet.
        # This ensures we can print Request + Response atomically later.
        agent_id = p.get("agent_id", "?")
        self._pending_requests[agent_id] = p
    
    def _print_request_details(self, p: dict) -> None:
        """Helper to print the request details from a buffered payload."""
        agent_id = p.get("agent_id", "?")
        
        # Always print header when starting a new block
        if agent_id != self._current_agent:
            self._current_agent = agent_id
            self._write_agent_header(p)
        
        phase = p.get("step", p.get("phase", "?"))
        self._write(f"\n── Turn ({phase}) {'─' * 40}")
        
        messages = p.get("messages")
        if messages and isinstance(messages, list):
            # If NOT including full prompts (default), only show the LAST message
            if not self._include_full_prompts and len(messages) > 0:
                messages_to_print = [messages[-1]]
                if len(messages) > 1:
                    self._write(f"\n... (hiding {len(messages) - 1} previous messages) ...")
            else:
                messages_to_print = messages

            for msg in messages_to_print:
                role = msg.get("role", "?").upper()
                content = msg.get("content", "")
                self._write(f"\n→ {role}:")
                self._write(textwrap.indent(str(content)[:2000], "  "))

    def _handle_model_response(self, p: dict) -> None:
        agent_id = p.get("agent_id", "?")
        
        # 1. Retrieve and print the buffered request (Atomic Turn)
        request_payload = self._pending_requests.pop(agent_id, None)
        if request_payload:
             self._print_request_details(request_payload)
        
        # 2. Print the response
        status = p.get("status", "?")
        duration = p.get("duration_ms", "?")
        tokens = p.get("total_tokens", "?")
        response = p.get("response_text", "")
        
        # Ensure we are logged under the correct agent header if no request was pending
        # (e.g. if we missed the request event for some reason)
        if agent_id != self._current_agent:
            self._current_agent = agent_id
            self._write_agent_header(p)
            
        self._write(f"\n← MODEL RESPONSE ({duration}ms, {tokens} tokens) [{status}]:")
        if response:
            self._write(textwrap.indent(str(response)[:2000], "  "))
        
        if p.get("error"):
            self._write(f"  ERROR: {p['error']}")
    
    def _handle_tool_call(self, p: dict) -> None:
        tool = p.get("tool_name", "?")
        self._write(f"\n  ⚙ TOOL CALL: {tool}")
    
    def _handle_tool_result(self, p: dict) -> None:
        tool = p.get("tool_name", "?")
        status = p.get("status", "?")
        output = p.get("tool_output", "")
        self._write(f"    → {tool} [{status}]")
        if output:
            self._write(textwrap.indent(str(output)[:1000], "      "))
    
    def _handle_submit_result(self, p: dict) -> None:
        status = p.get("status", "?")
        agent_id = p.get("agent_id", "?")
        self._write(f"\n{'═' * 60}")
        self._write(f"RESULT: {status} | Agent: {agent_id}")
        self._write(f"{'═' * 60}\n")
        self._current_agent = None
    
    def _handle_agent_error(self, p: dict) -> None:
        agent_id = p.get("agent_id", "?")
        
        # Flush any pending request for this agent so we see what caused the error
        request_payload = self._pending_requests.pop(agent_id, None)
        if request_payload:
             self._print_request_details(request_payload)

        self._write(f"\n{'!' * 60}")
        self._write(f"AGENT ERROR: {p.get('error', '?')}")
        self._write(f"  Agent: {p.get('agent_id')} | Phase: {p.get('phase')}")
        if p.get("error_code"):
            self._write(f"  Code: {p['error_code']}")
        self._write(f"{'!' * 60}\n")
    
    def _write_agent_header(self, p: dict) -> None:
        self._write(f"\n{'═' * 60}")
        self._write(f"AGENT: {p.get('agent_id', '?')} | Op: {p.get('operation', '?')}")
        self._write(f"Model: {p.get('model', '?')}")
        self._write(f"Time: {datetime.now(timezone.utc).isoformat()}")
        self._write(f"{'═' * 60}")
