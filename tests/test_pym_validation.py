"""Validate every .pym file with grail check --strict."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.grail_runtime

PYM_FILES = list((Path(__file__).parent.parent / "agents").rglob("*.pym"))


@pytest.mark.parametrize("pym_path", PYM_FILES, ids=lambda p: p.stem)
def test_grail_check_strict(pym_path: Path) -> None:
    import grail

    script = grail.load(pym_path)
    result = script.check()
    error_text = "\n".join(str(message) for message in result.errors)
    warning_text = "\n".join(str(message) for message in result.warnings)
    assert result.valid, f"{pym_path} failed grail check:\n" + error_text
    assert not result.warnings, f"{pym_path} produced grail warnings:\n" + warning_text
