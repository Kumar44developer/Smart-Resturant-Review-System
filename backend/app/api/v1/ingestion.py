from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status

from ...config import settings
from ...deps import current_user, enforce_role, get_db
from ...repo import ops as orepo
from ...services import csv_import, jobs

router = APIRouter(tags=["imports"])


def _read_csv(file: UploadFile) -> str:
    name = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()
    if not (name.endswith(".csv") or "csv" in ctype or "text" in ctype):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .csv uploads are accepted")
    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"File exceeds {settings.max_upload_mb} MB limit")
    try:
        return csv_import.decode_bytes(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post("/restaurants/{restaurant_id}/imports/preview")
def preview(restaurant_id: int, file: UploadFile, user: dict = Depends(current_user),
            conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "member")
    text = _read_csv(file)
    try:
        result = csv_import.process(conn, restaurant_id, text)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "columns": result["columns"], "counts": result["counts"],
        "total_rows": result["total_rows"],
        "sample_valid": result["valid"][:10],
        "sample_invalid": result["invalid"][:10],
    }


@router.post("/restaurants/{restaurant_id}/imports", status_code=status.HTTP_202_ACCEPTED)
def start_import(restaurant_id: int, file: UploadFile, background: BackgroundTasks,
                 analyze: bool = True,
                 user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "member")
    text = _read_csv(file)
    try:
        csv_import.process(conn, restaurant_id, text)  # validate header early
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    job = orepo.create_job(conn, restaurant_id, file.filename or "upload.csv", user["id"])
    background.add_task(jobs.run_import_job, job["id"], restaurant_id, text,
                        created_by=user["id"], analyze=analyze)
    return {"job_id": job["id"], "status": "queued"}


@router.get("/imports/{job_id}")
def job_status(job_id: int, user: dict = Depends(current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    job = orepo.get_job(conn, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    enforce_role(conn, user, job["restaurant_id"], "viewer")  # tenant check before returning
    return job
