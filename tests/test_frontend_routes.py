import pytest

stario = pytest.importorskip("stario")
from stario import RichTracer, Stario

from remora.frontend import WorkspaceInboxCoordinator, register_routes


def test_register_routes_creates_coordinator_and_routes() -> None:
    tracer = RichTracer()
    app = Stario(tracer)

    coordinator = register_routes(app)

    assert isinstance(coordinator, WorkspaceInboxCoordinator)
    assert hasattr(app, "routes")
