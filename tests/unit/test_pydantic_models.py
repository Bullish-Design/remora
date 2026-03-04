"""TDD tests for 6.6: Delete stdlib dataclass models in remora.models.

Verifies:
- All models in remora.models are Pydantic BaseModel instances
- to_dict() returns plain dicts (via model_dump)
- from_dict / from_config classmethods work
- No stdlib dataclass imports remain
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel

from remora.core.config import Config
from remora.models import (
    ConfigSnapshot,
    InputResponse,
    SwarmEmitRequest,
    SwarmEmitResponse,
)


class TestModelsArePydantic:
    """All models in remora.models should be Pydantic BaseModel."""

    @pytest.mark.parametrize(
        "cls",
        [SwarmEmitRequest, SwarmEmitResponse, InputResponse, ConfigSnapshot],
    )
    def test_is_pydantic_basemodel(self, cls):
        assert issubclass(cls, BaseModel), f"{cls.__name__} should be a Pydantic BaseModel"

    def test_no_dataclass_import(self):
        """The models module should not import from dataclasses."""
        import remora.models as mod

        source = inspect.getsource(mod)
        assert "from dataclasses" not in source, "remora.models should not import from dataclasses"


class TestSwarmEmitRequest:
    def test_construction(self):
        req = SwarmEmitRequest(event_type="TestEvent", data={"key": "val"})
        assert req.event_type == "TestEvent"
        assert req.data == {"key": "val"}

    def test_to_dict(self):
        req = SwarmEmitRequest(event_type="TestEvent", data={"key": "val"})
        d = req.to_dict()
        assert isinstance(d, dict)
        assert d["event_type"] == "TestEvent"

    def test_from_dict(self):
        req = SwarmEmitRequest.from_dict({"event_type": "  Foo  ", "data": {"a": 1}})
        assert req.event_type == "Foo"
        assert req.data == {"a": 1}

    def test_from_dict_empty(self):
        req = SwarmEmitRequest.from_dict({})
        assert req.event_type == ""
        assert req.data == {}


class TestSwarmEmitResponse:
    def test_construction(self):
        resp = SwarmEmitResponse(event_id=42)
        assert resp.event_id == 42

    def test_to_dict(self):
        resp = SwarmEmitResponse(event_id=42)
        d = resp.to_dict()
        assert d == {"event_id": 42}


class TestInputResponse:
    def test_construction(self):
        resp = InputResponse(request_id="r1")
        assert resp.request_id == "r1"
        assert resp.status == "submitted"

    def test_to_dict(self):
        resp = InputResponse(request_id="r1", status="done")
        d = resp.to_dict()
        assert d == {"request_id": "r1", "status": "done"}


class TestConfigSnapshot:
    def test_from_config(self):
        config = Config(model_default="my-model")
        snap = ConfigSnapshot.from_config(config)
        assert snap.model["default_model"] == "my-model"
        assert isinstance(snap.discovery, dict)
        assert isinstance(snap.execution, dict)

    def test_to_dict(self):
        config = Config()
        snap = ConfigSnapshot.from_config(config)
        d = snap.to_dict()
        assert isinstance(d, dict)
        assert "discovery" in d
        assert "model" in d
