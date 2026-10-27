"""Server-rendered web UI (FastAPI + Jinja2 + HTMX).

Chosen deliberately over a Node/SPA build: it runs with zero native binaries and
no build step, which is required in this environment (Smart App Control blocks the
compiled wheels and no admin is available to change that). It shares the exact
same service layer and the ``srr_session`` cookie as the JSON API, so there is a
single source of truth - the UI never recomputes or invents a metric; it renders
what the analytics/RAG services return. HTMX/Chart.js progressively enhance; every
page still works as plain server-rendered HTML without JavaScript."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE.parent / "templates"
STATIC_DIR = HERE.parent / "static"


def mount_web(app: FastAPI) -> None:
    from .routes import router, templates  # imported here to bind app-level deps

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.state.templates = templates
    app.include_router(router)
