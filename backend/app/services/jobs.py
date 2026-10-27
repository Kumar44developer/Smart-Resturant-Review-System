"""Background jobs for imports + batch analysis.

Runs on FastAPI's in-process BackgroundTasks (documented). Celery + Redis is the
production alternative; it is intentionally NOT introduced here because it would
be appearance-only on this single-machine, SQLite deployment. Each task opens its
own SQLite connection because it runs on a worker thread. See docs/DEPLOYMENT.md."""
from __future__ import annotations

import logging

from .. import db
from ..repo import reviews as rrepo
from . import analysis as analysis_svc
from . import csv_import

log = logging.getLogger("services.jobs")


def run_import_job(job_id: int, restaurant_id: int, text: str, *, source_default="csv",
                   created_by=None, analyze: bool = True) -> dict:
    conn = db.connect()
    try:
        result = csv_import.commit(conn, job_id, restaurant_id, text,
                                   source_default=source_default, created_by=created_by)
        if analyze:
            new_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM reviews WHERE restaurant_id=? AND analysis_status='pending' "
                "ORDER BY id DESC LIMIT ?", (restaurant_id, result["inserted"])
            ).fetchall()]
            for rid in new_ids:
                try:
                    analysis_svc.analyze_review(conn, rid, user_id=created_by, operation="import_analysis")
                except Exception as exc:  # noqa: BLE001
                    log.warning("import analysis failed", extra={"ctx": {"review_id": rid, "err": str(exc)}})
        return result
    finally:
        conn.close()


def analyze_pending(conn, restaurant_id: int, *, limit: int = 500) -> dict:
    """Synchronous batch analysis for authorized, on-demand reanalysis."""
    pending = [r["id"] for r in conn.execute(
        "SELECT id FROM reviews WHERE restaurant_id=? AND analysis_status IN ('pending','failed','stale') "
        "ORDER BY id LIMIT ?", (restaurant_id, limit)
    ).fetchall()]
    ok = fail = 0
    for rid in pending:
        try:
            analysis_svc.analyze_review(conn, rid, operation="batch_analysis")
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
    return {"analyzed": ok, "failed": fail, "requested": len(pending)}
