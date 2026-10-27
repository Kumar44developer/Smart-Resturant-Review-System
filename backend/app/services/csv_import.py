"""CSV import pipeline (stdlib csv only). Handles encoding, column aliases,
rating/date normalization, per-row validation, duplicate detection, preview,
and transactional commit with row-level error reporting. Uploaded content is
treated strictly as data - never executed."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from ..repo import reviews as rrepo

COLUMN_ALIASES: dict[str, list[str]] = {
    "review_text": ["review_text", "review", "text", "comment", "body", "content"],
    "rating": ["rating", "stars", "score", "overall_rating"],
    "date": ["date", "review_date", "created", "when", "timestamp", "reviewed_at"],
    "author": ["author", "name", "reviewer", "customer", "user", "username", "author_name"],
    "source": ["source", "platform", "channel", "site"],
    "external_id": ["external_id", "review_id", "source_id", "id", "uid", "ext_id"],
}

MAX_CELL_CHARS = 5000


def decode_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported file encoding")


def _build_alias_lookup(header: list[str]) -> dict[str, int]:
    norm = [(h or "").strip().lower() for h in header]
    lookup: dict[str, int] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                lookup[field] = norm.index(alias)
                break
    return lookup


def normalize_rating(value: Any) -> tuple[float | None, str | None]:
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip().lower()
    token = raw.split("/")[0].strip().replace("stars", "").replace("star", "").strip()
    try:
        num = float(token)
    except ValueError:
        return None, f"invalid rating '{value}'"
    if num > 5:  # tolerate 1-10 or 1-100 scales
        num = num / (10 if num <= 10 else 20)
    num = max(1.0, min(5.0, round(num, 1)))
    return num, None


def normalize_date(value: Any) -> tuple[str | None, str | None]:
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw[:19], fmt).isoformat(sep=" "), None
        except ValueError:
            continue
    return None, f"invalid date '{value}'"


def _row_fields(row: list[str], lookup: dict[str, int]) -> dict[str, Any]:
    def get(field: str) -> Any:
        idx = lookup.get(field)
        return row[idx] if idx is not None and idx < len(row) else None
    return {
        "review_text": get("review_text"),
        "rating": get("rating"),
        "date": get("date"),
        "author": get("author"),
        "source": get("source"),
        "external_id": get("external_id"),
    }


def process(conn, restaurant_id: int, text: str, *, source_default: str = "csv",
            seen_external_ids: set[str] | None = None) -> dict:
    """Parse + validate every row against the DB. Returns classified rows + counts.
    Does NOT write. Used by both preview and commit."""
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("empty file")
    lookup = _build_alias_lookup(header)
    if "review_text" not in lookup:
        raise ValueError("required 'review text' column not found (aliases: "
                         + ", ".join(COLUMN_ALIASES["review_text"]) + ")")

    seen = seen_external_ids if seen_external_ids is not None else set()
    valid: list[dict] = []
    duplicates: list[dict] = []
    invalid: list[dict] = []

    for i, row in enumerate(reader, start=2):  # line 1 is header
        if not any((cell or "").strip() for cell in row):
            continue  # silently skip blank lines
        f = _row_fields(row, lookup)
        errors: list[str] = []

        body = (f["review_text"] or "").strip()
        if not body:
            errors.append("missing review text")
        elif len(body) > MAX_CELL_CHARS:
            errors.append(f"review text exceeds {MAX_CELL_CHARS} chars")

        rating, rerr = normalize_rating(f["rating"])
        if rerr:
            errors.append(rerr)
        date, derr = normalize_date(f["date"])
        if derr:
            errors.append(derr)

        source = (f["source"] or source_default).strip() or source_default
        ext_id = (str(f["external_id"]).strip() if f["external_id"] else None) or None

        if errors:
            invalid.append({"row": i, "message": "; ".join(errors), "raw": row})
            continue

        is_dup = False
        if ext_id:
            if ext_id in seen or rrepo.duplicate_exists(conn, restaurant_id, source, ext_id):
                is_dup = True
            seen.add(ext_id)

        record = {
            "row": i, "review_text": body, "rating": rating, "review_ts": date,
            "author_name": (f["author"] or None), "source": source, "external_source_id": ext_id,
        }
        (duplicates if is_dup else valid).append(record)

    return {
        "columns": lookup,
        "total_rows": len(valid) + len(duplicates) + len(invalid),
        "valid": valid, "duplicates": duplicates, "invalid": invalid,
        "counts": {"imported": len(valid), "duplicate": len(duplicates), "invalid": len(invalid)},
    }


def commit(conn, job_id: int, restaurant_id: int, text: str, *, source_default: str = "csv",
           created_by: int | None = None, create_review_fn=None) -> dict:
    """Persist valid rows transactionally, recording row-level errors on the job."""
    from ..repo import ops as orepo
    result = process(conn, restaurant_id, text, source_default=source_default)
    create = create_review_fn or rrepo.create_review
    inserted = 0
    orepo.update_job(conn, job_id, status="running", total_rows=result["total_rows"])
    try:
        conn.execute("BEGIN")
        for rec in result["valid"]:
            create(
                conn, restaurant_id, rec["review_text"], rating=rec["rating"],
                source=rec["source"], external_source_id=rec["external_source_id"],
                author_name=rec["author_name"], review_ts=rec["review_ts"],
            )
            inserted += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    errors = result["invalid"] + [{"row": d["row"], "message": "duplicate external id"}
                                  for d in result["duplicates"]]
    status = "completed" if not errors else "completed_with_errors"
    orepo.update_job(
        conn, job_id, status=status, imported=inserted, duplicate_count=len(result["duplicates"]),
        invalid_count=len(result["invalid"]), skipped=len(result["duplicates"]),
        error_details=errors, completed_at=datetime.now(timezone.utc).isoformat(sep=" ", timespec="seconds"),
    )
    return {"job_id": job_id, "status": status, "inserted": inserted,
            "duplicates": len(result["duplicates"]), "invalid": len(result["invalid"]),
            "total_rows": result["total_rows"]}
