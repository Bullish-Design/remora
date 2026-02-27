"""Run the Remora UI component demo."""

from __future__ import annotations

import argparse

import uvicorn

from demo.component_demo.app import create_demo_app


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
