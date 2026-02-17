# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "openai",
# ]
# ///
#
# Verify that the vLLM server is reachable and responding correctly.
#
# Run from any Tailscale-connected machine (no virtualenv needed):
#   uv run server/test_connection.py
#
# Or point at a specific host:
#   SERVER_URL=http://100.x.x.x:8000/v1 uv run server/test_connection.py

import asyncio
import os

from openai import AsyncOpenAI

SERVER_URL = os.environ.get("SERVER_URL", "http://function-gemma-server:8000/v1")
MODEL_NAME = os.environ.get("MODEL_NAME", "google/functiongemma-270m-it")


async def test_base_model() -> None:
    print(f"Connecting to vLLM at {SERVER_URL}...")

    client = AsyncOpenAI(base_url=SERVER_URL, api_key="EMPTY")

    try:
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with exactly: 'Connection successful.'"},
            ],
            max_tokens=20,
            temperature=0.1,
        )
        reply = response.choices[0].message.content or ""
        print(f"SUCCESS: {reply.strip()}")
    except Exception as exc:
        print(f"FAILED: {exc}")
        print("Check: Is the container fully booted? Is Tailscale connected?")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(test_base_model())
