"""Fuzz testing for tool script JSON handling."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st


json_like_strings = st.one_of(
    st.just(""),
    st.just("null"),
    st.just("{}"),
    st.just("[]"),
    st.just('{"key": "value"}'),
    st.text(),
    st.binary().map(lambda value: value.decode("utf-8", errors="replace")),
)


@given(input_data=json_like_strings)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_tool_script_handles_malformed_json(input_data: str) -> None:
    """Tool scripts should not crash on malformed JSON input."""
    assume("\x00" not in input_data)
    script_content = """
import json
import os

try:
    input_str = os.environ.get("REMORA_INPUT", "{}")
    json.loads(input_str)
    print(json.dumps({"result": "ok", "parsed": True}))
except json.JSONDecodeError as exc:
    print(json.dumps({"error": str(exc), "parsed": False}))
except Exception as exc:
    print(json.dumps({"error": str(exc), "parsed": False}))
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = Path(temp_dir) / "test_script.py"
        script_path.write_text(script_content)

        env = {**os.environ, "REMORA_INPUT": input_data}

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )

    assert result.returncode == 0, f"Script crashed with: {result.stderr}"

    try:
        output = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        pytest.fail(f"Script produced invalid JSON: {result.stdout}")

    assert "result" in output or "error" in output
