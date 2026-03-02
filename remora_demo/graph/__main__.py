"""CLI entry point: python -m remora_demo.graph [--port 8420] [--db PATH]."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Remora force-directed graph viewer")
    parser.add_argument("--port", type=int, default=8420, help="HTTP port (default: 8420)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--db", default=".remora/indexer.db", help="Path to indexer.db")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    from remora_demo.graph.app import create_app

    app = create_app(db_path=args.db)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
