"""FastAPI application factory and assembly.

Run (from backend/):  python -m uvicorn app.main:app --reload
The lifespan hook applies pending migrations on startup so a fresh checkout boots
with the schema ready. Observability middleware assigns a request id and emits a
structured access log (never bodies or secrets). Error handlers return a consistent
{"error": {...}} envelope for the versioned API."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, migrations
from .api.v1 import api_router
from .config import settings
from .logging_setup import configure_logging, new_request_id, request_id_var

log = logging.getLogger("app.access")
app_log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging("WARNING" if settings.is_prod else "INFO")
    conn = db.connect()
    try:
        applied = migrations.migrate(conn)
        if applied:
            app_log.info("applied migrations", extra={"ctx": {"migrations": applied}})
    finally:
        conn.close()
    app_log.info("startup complete", extra={"ctx": {
        "env": settings.app_env, "demo_mode": settings.demo_mode,
        "ai_provider": "demo" if settings.demo_mode else settings.ai_provider,
    }})
    yield
    db.close_conn()


app = FastAPI(
    title="Smart Restaurant Review Intelligence Platform",
    version="1.0.0",
    description="Turn restaurant reviews into evidence-linked, human-approved insight.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        request_id_var.reset(token)
    response.headers["x-request-id"] = rid
    response.headers["x-process-time-ms"] = str(elapsed_ms)
    log.info("request", extra={"ctx": {
        "method": request.method, "path": request.url.path,
        "status": response.status_code, "ms": elapsed_ms,
    }})
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": 422, "message": "Request validation failed",
                           "details": exc.errors()}},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    app_log.exception("unhandled error", extra={"ctx": {"path": request.url.path}})
    # Never leak internals to clients.
    return JSONResponse(status_code=500,
                        content={"error": {"code": 500, "message": "Internal server error"}})


app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
def health():
    """Liveness: the process is up. No external dependencies probed."""
    return {"status": "ok", "service": "smart-review-api", "demo_mode": settings.demo_mode}


@app.get("/ready", tags=["system"])
def readiness():
    """Readiness: the database is reachable and the schema is migrated."""
    try:
        conn = db.connect()
        conn.execute("SELECT 1").fetchone()
        applied = sorted(migrations.applied(conn))
        conn.close()
        return {"status": "ready", "database": "ok", "migrations": len(applied),
                "demo_mode": settings.demo_mode}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503,
                            content={"status": "not-ready", "database": str(exc)})


# The server-rendered UI is added in app.web and mounted when present.
try:  # pragma: no cover - optional until the web layer exists
    from .web import mount_web

    mount_web(app)
except Exception:  # noqa: BLE001
    pass
