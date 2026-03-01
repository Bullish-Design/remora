"""Run the Remora UI component demo."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[2]
print(f"\nRunning Demo from repo root: {REPO_ROOT}\n")
for root in (REPO_ROOT, Path.cwd().resolve()):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

try:
    from demo.component_demo.app import create_demo_app  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - fallback for script execution
    if exc.name != "demo.component_demo":
        raise
    module_path = Path(__file__).resolve().parent / "app.py"
    spec = importlib.util.spec_from_file_location("component_demo_app", module_path)
    if spec is None or spec.loader is None:
        raise
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    create_demo_app = module.create_demo_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Remora UI component demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8425, type=int)
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--project-root", dest="project_root", default=None)
    args = parser.parse_args()

    app = create_demo_app(
        config_path=args.config_path,
        project_root=args.project_root,
    )

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
