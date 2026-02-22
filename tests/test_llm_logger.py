from __future__ import annotations

from remora.events import EventName
from remora.llm_logger import LlmConversationLogger


def test_logger_writes_warning_without_model_request(tmp_path) -> None:
    logger = LlmConversationLogger(output=tmp_path)
    logger.open()

    logger.emit({"agent_id": "agent-1", "event": EventName.AGENT_COMPLETE})

    logger.close()

    log_files = list(tmp_path.glob("llm_conversations_*.log"))
    assert log_files
    content = log_files[0].read_text(encoding="utf-8")
    assert "WARNING: No model_request found" in content
    assert "AGENT: agent-1" in content
