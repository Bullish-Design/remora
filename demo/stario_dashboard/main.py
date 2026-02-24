import asyncio
from pathlib import Path

from stario import RichTracer, Stario
from stario.http.writer import CompressionConfig

from . import dashboard_state
from . import handlers
from . import views

tracer = RichTracer()

with tracer:
    app = Stario(tracer, compression=CompressionConfig())

    app.assets("/static", Path(__file__).parent / "static")

    app.get("/", handlers.home)
    app.get("/events", handlers.events)
    app.post("/agent/{agent_id}/respond", handlers.respond)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
