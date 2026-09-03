"""CSV Import Job API — Phase 6.

Two-phase import workflow:
  1. Create a job (POST /import-jobs)
  2. Upload CSV text → server generates a preview (POST /<id>/upload)
  3. Confirm the preview → data is committed (POST /<id>/confirm)

Supplier isolation: a supplier may only confirm jobs that belong to their
own supplier_id. Admins may act on any job.

URL structure:
  POST /api/v1/import-jobs
  POST /api/v1/import-jobs/<id>/upload
  POST /api/v1/import-jobs/<id>/confirm
  GET  /api/v1/import-jobs
  GET  /api/v1/import-jobs/<id>
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import csv_import_service

bp = Blueprint("import_jobs", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int_field(body: dict, name: str, required: bool = True, default=None):
    val = body.get(name, default)
    if val is None:
        if required:
            raise ValidationError(f"فیلد «{name}» الزامی است")
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValidationError(f"مقدار «{name}» باید عدد صحیح باشد")


def _is_admin() -> bool:
    return g.current_user.get("role") == "admin"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/import-jobs")
@require_auth("supplier", "admin")
def create_import_job():
    """Create a new CSV import job (no data yet — just the job shell)."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    supplier_id          = _int_field(body, "supplier_id")
    filename             = (body.get("filename") or "").strip()
    connector_account_id = _int_field(body, "connector_account_id", required=False)
    column_mapping       = body.get("column_mapping")  # dict or None

    if not filename:
        raise ValidationError("فیلد «filename» الزامی است")

    with db.write_transaction() as conn:
        job = csv_import_service.create_import_job(
            conn,
            supplier_id=supplier_id,
            filename=filename,
            connector_account_id=connector_account_id,
            column_mapping=column_mapping,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": job}), 201


@bp.post("/import-jobs/<int:job_id>/upload")
@require_auth("supplier", "admin")
def upload_csv(job_id: int):
    """Submit CSV text for an existing job; returns preview rows."""
    db   = get_db()
    body = request.get_json(silent=True) or {}

    csv_text = body.get("csv_text", "")
    if not csv_text or not csv_text.strip():
        raise ValidationError("فیلد «csv_text» نمی‌تواند خالی باشد")

    with db.write_transaction() as conn:
        job = csv_import_service.submit_csv_for_import(
            conn,
            job_id=job_id,
            csv_text=csv_text,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": job})


@bp.post("/import-jobs/<int:job_id>/confirm")
@require_auth("supplier", "admin")
def confirm_import(job_id: int):
    """Confirm a previewing import job and commit the data."""
    db = get_db()

    with db.read_transaction() as conn:
        job = csv_import_service.get_import_job(conn, job_id=job_id)

    if job is None:
        raise NotFoundError("جاب ایمپورت یافت نشد")

    # Supplier isolation: non-admins may only confirm their own jobs
    if not _is_admin():
        with db.read_transaction() as conn:
            sup = conn.execute(
                "SELECT id FROM suppliers WHERE user_id = ?",
                (g.current_user["id"],),
            ).fetchone()
        if sup is None or int(job.get("supplier_id", -1)) != sup["id"]:
            raise NotFoundError("جاب ایمپورت یافت نشد")

    with db.write_transaction() as conn:
        summary = csv_import_service.confirm_import(
            conn,
            job_id=job_id,
            actor_user_id=g.current_user["id"],
        )
    return jsonify({"data": summary})


@bp.get("/import-jobs")
@require_auth("supplier", "admin")
def list_import_jobs():
    """List import jobs, optionally filtered by supplier."""
    db          = get_db()
    supplier_id = request.args.get("supplier_id", type=int)
    limit       = min(int(request.args.get("limit", "20")), 200)
    offset      = int(request.args.get("offset", "0"))

    with db.read_transaction() as conn:
        jobs = csv_import_service.list_import_jobs(
            conn,
            supplier_id=supplier_id,
            limit=limit,
            offset=offset,
        )
    return jsonify({"data": jobs})


@bp.get("/import-jobs/<int:job_id>")
@require_auth("supplier", "admin")
def get_import_job(job_id: int):
    """Get a single import job by ID."""
    db = get_db()
    with db.read_transaction() as conn:
        job = csv_import_service.get_import_job(conn, job_id=job_id)
    if job is None:
        raise NotFoundError("جاب ایمپورت یافت نشد")
    return jsonify({"data": job})
