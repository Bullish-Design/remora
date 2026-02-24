from pathlib import Path

from stario import RichTracer, Stario
from stario.http.writer import CompressionConfig

from remora.frontend import register_routes

tracer = RichTracer()

with tracer:
    app = Stario(tracer, compression=CompressionConfig())

    app.assets("/static", Path(__file__).parent / "static")

    register_routes(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
