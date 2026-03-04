"""Entry point for the Remora Graph Viewer.

Usage::

    python -m remora_demo.web.graph --port 8420 --db .remora/indexer.db

Requires Python 3.14 and Stario.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remora Graph Viewer -- real-time agent graph visualization",
    )
    parser.add_argument("--port", type=int, default=8420, help="HTTP port (default: 8420)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument(
        "--db",
        default=".remora/indexer.db",
        help="Path to the shared SQLite DB (default: .remora/indexer.db)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.3,
        help="DB poll interval in seconds (default: 0.3)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    db_path = Path(args.db)
    if not db_path.exists():
        print(
            f"Warning: DB not found at {db_path}. Will wait for LSP server to create it.",
            file=sys.stderr,
        )

    print(f"Remora Graph Viewer: http://{args.host}:{args.port}")
    print(f"DB: {db_path.resolve()}")
    print(f"Poll interval: {args.poll_interval}s")

    asyncio.run(_serve(args))


async def _serve(args: argparse.Namespace) -> None:
    from remora_demo.web.graph.app import create_app

    app, bridge = create_app(db_path=str(args.db), poll_interval=args.poll_interval)
    asyncio.create_task(bridge.run())
    await app.serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
