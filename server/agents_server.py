from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", "/app/agents")).resolve()

app = FastAPI()

app.mount("/agents", StaticFiles(directory=str(AGENTS_DIR)), name="agents")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "agents_dir": str(AGENTS_DIR)}
