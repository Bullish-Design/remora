from __future__ import annotations

import tomllib
from pathlib import Path


def test_remora_lsp_package_exports_main() -> None:
    import remora.lsp as lsp

    assert callable(lsp.main)


def test_remora_lsp_console_script_targets_module_main() -> None:
    pyproject = Path("pyproject.toml")
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]
    assert scripts["remora-lsp"] == "remora.lsp.__main__:main"
