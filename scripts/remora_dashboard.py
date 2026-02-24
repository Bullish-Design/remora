"""Stario Dashboard - Real-time agent dashboard using SSE + Datastar."""

import asyncio

from stario import RichTracer, Stario
from stario.http.writer import CompressionConfig

from demo.stario_dashboard import dashboard_state
from demo.stario_dashboard import handlers
from demo.stario_dashboard import views


def main():
    tracer = RichTracer()

    with tracer:
        app = Stario(tracer, compression=CompressionConfig())

        app.assets("/static", "demo/stario_dashboard/static")

        app.get("/", handlers.home)
        app.get("/events", handlers.events)
        app.post("/agent/{agent_id}/respond", handlers.respond)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
