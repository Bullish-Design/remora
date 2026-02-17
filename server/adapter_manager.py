#!/usr/bin/env python3
"""Manage vLLM LoRA adapters via the server API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_SERVER_URL = "http://remora-server:8000/v1"


def build_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    return f"{base_url}/load_lora_adapter"


def load_adapter(server_url: str, lora_name: str, lora_path: str, timeout: int) -> None:
    payload = json.dumps({"lora_name": lora_name, "lora_path": lora_path}).encode("utf-8")
    request = urllib.request.Request(
        build_url(server_url),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            print(f"SUCCESS: {response.status} {response.reason}")
            if body:
                print(body)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8") if exc.fp else ""
        print(f"FAILED: {exc.code} {exc.reason}")
        if error_body:
            print(error_body)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"FAILED: {exc.reason}")
        raise SystemExit(1) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load a LoRA adapter into vLLM without restart.")
    parser.add_argument("--name", required=True, help="Adapter name (lora_name).")
    parser.add_argument("--path", required=True, help="Absolute path to adapter on server.")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("SERVER_URL", DEFAULT_SERVER_URL),
        help="Base vLLM URL (default: %(default)s).",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_adapter(args.server_url, args.name, args.path, args.timeout)


if __name__ == "__main__":
    main()
