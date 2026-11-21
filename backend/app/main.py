"""Application entry point.

    uvicorn app.main:app --port 8000

Starts the delivery dispatcher and in-process SOC workers unless TRINETRA_WORKERS=0
(run `python -m app.soc.worker` separately for independent worker processes).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth
from .analyst.intelligence_api import router as analyst_router
from .api import health, router, soc
from .config import settings
from .db import get_db
from .events import Dispatcher
from .inference import get_runtime
from .soc.worker import Worker

log = logging.getLogger("trinetra")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    rt = get_runtime()
    for m in rt.manifest.describe():
        log.info("model %s: %s (%s)", m["key"], m["status"], m["reason"])
    if not settings.analyst_passcode:
        auth.analyst_passcode()
        log.info("analyst passcode written to %s", settings.data_dir / "analyst-passcode.txt")
    threads = [Dispatcher(db)] + [Worker(db, i) for i in range(settings.in_process_workers)]
    for t in threads:
        t.start()
    yield
    for t in threads:
        t.stop()


def create_app(start_background: bool = True) -> FastAPI:
    app = FastAPI(title="TRINETRA Digital Trust and Cybersecurity", version="2.0.0",
                  lifespan=lifespan if start_background else None)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(x) for x in first.get("loc", [])[1:])
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_request", "field": field,
                                                                 "message": "Check the highlighted field and try again."}})

    app.include_router(router)
    app.include_router(soc)
    app.include_router(analyst_router)
    app.get("/api/health")(health)

    if settings.serve_frontend and settings.serve_frontend.exists():
        dist = settings.serve_frontend
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # Keep signed upload URLs out of request logs.
app = create_app()
