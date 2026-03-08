"""CLI entrypoint for quick bootstrap runtime checks."""

from __future__ import annotations

import json

from remora_bootstrap.runtime import BootstrapRuntime


def main() -> None:
    runtime = BootstrapRuntime.create()
    print(json.dumps(runtime.registry.summary(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
