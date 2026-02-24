from pathlib import Path

import asyncio
import traceback
from remora.frontend import register_routes
from stario import RichTracer, Stario
from stario.http.writer import CompressionConfig

tracer = RichTracer()

with tracer:
    app = Stario(tracer, compression=CompressionConfig())

    app.assets("/static", Path(__file__).parent / "static")

    def error_handler(c, w, exc):
        w.text(f"Error: {exc}\n{traceback.format_exc()}", 500)

    app.on_error(Exception, error_handler)

    register_routes(app)


def main() -> None:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(app.serve(host="0.0.0.0", port=8000))


if __name__ == "__main__":
    main()
