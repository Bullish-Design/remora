"""CLI entrypoint for persistent ID indexing template."""

from __future__ import annotations

import argparse
from pathlib import Path

from persistent_ids.pipeline.annotator import annotate_missing_ids
from persistent_ids.pipeline.indexer import PersistentIdIndexer
from persistent_ids.settings import IndexerSettings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persistent-ids")
    sub = parser.add_subparsers(dest="command", required=True)

    init_db = sub.add_parser("init-db", help="Initialize SQLite schema")
    init_db.add_argument("--db", type=Path, required=True)

    index = sub.add_parser("index", help="Index files under repo root")
    index.add_argument("--db", type=Path, required=True)
    index.add_argument("--root", type=Path, required=True)

    annotate = sub.add_parser("annotate", help="Plan/apply missing graph:id writeback")
    annotate.add_argument("path", type=Path)
    annotate.add_argument("--apply", action="store_true", help="Apply edits")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        settings = IndexerSettings(repo_root=Path("."), db_path=args.db)
        indexer = PersistentIdIndexer(settings)
        try:
            indexer.init_db()
        finally:
            indexer.close()
        return

    if args.command == "index":
        settings = IndexerSettings(repo_root=args.root, db_path=args.db)
        indexer = PersistentIdIndexer(settings)
        try:
            indexer.init_db()
            indexer.index_paths()
        finally:
            indexer.close()
        return

    if args.command == "annotate":
        result = annotate_missing_ids(args.path, dry_run=not args.apply)
        print(result)
        return

    parser.error(f"Unknown command: {args.command}")
