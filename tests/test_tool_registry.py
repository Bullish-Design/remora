from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from remora.errors import AGENT_001
from remora.tool_registry import (
    GrailInputSpec,
    GrailToolRegistry,
    ToolRegistryError,
    _build_parameters,
    _load_inputs,
)


class DummyTool:
    def __init__(self, pym: Path, tool_description: str, inputs_override=None, tool_name: str | None = None) -> None:
        self.pym = pym
        self.tool_description = tool_description
        self.inputs_override = inputs_override or {}
        self.tool_name = tool_name

    @property
    def name(self) -> str:
        return self.tool_name or self.pym.stem


def test_build_tool_catalog_reads_inputs(monkeypatch, tmp_path: Path) -> None:
    grail_root = tmp_path / "grail"
    artifact_dir = grail_root / "demo"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "inputs.json").write_text(
        json.dumps({"inputs": [{"name": "path", "type": "str", "required": True, "default": None}]}),
        encoding="utf-8",
    )

    class FakeScript:
        name = "demo"

        def check(self):
            return SimpleNamespace(valid=True, warnings=[], errors=[])

    monkeypatch.setattr("remora.tool_registry.grail.load", lambda *_args, **_kwargs: FakeScript())

    tool_path = tmp_path / "demo.pym"
    tool_path.write_text("", encoding="utf-8")
    tool = DummyTool(tool_path, "Demo tool", inputs_override={"path": {"description": "Target path"}})

    registry = GrailToolRegistry(grail_root)
    catalog = registry.build_tool_catalog([tool])

    schema = catalog.schemas[0]
    assert schema["function"]["name"] == "demo"
    params = schema["function"]["parameters"]
    assert params["properties"]["path"]["description"] == "Target path"
    assert "path" in params["required"]


def test_preflight_check_all_raises_on_invalid(monkeypatch, tmp_path: Path) -> None:
    class FakeScript:
        name = "bad"

        def check(self):
            return SimpleNamespace(valid=False, warnings=[], errors=[SimpleNamespace(message="broken")])

    monkeypatch.setattr("remora.tool_registry.grail.load", lambda *_args, **_kwargs: FakeScript())

    tool_path = tmp_path / "bad.pym"
    tool_path.write_text("", encoding="utf-8")
    tool = DummyTool(tool_path, "Bad tool")

    registry = GrailToolRegistry(tmp_path)

    with pytest.raises(ToolRegistryError) as excinfo:
        registry.preflight_check_all([tool])

    assert excinfo.value.code == AGENT_001


def test_load_inputs_invalid_json(tmp_path: Path) -> None:
    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(ToolRegistryError):
        _load_inputs(inputs_path, Path("tool.pym"))


def test_build_parameters_warns_on_override_mismatch() -> None:
    inputs = [GrailInputSpec(name="count", type="int", required=True, default=1)]

    with pytest.warns(UserWarning) as record:
        _build_parameters(
            inputs,
            {"count": {"type": "string", "default": 2, "required": False}, "extra": {"type": "string"}},
            Path("tool.pym"),
        )

    assert any("inputs_override" in str(warning.message) for warning in record)
