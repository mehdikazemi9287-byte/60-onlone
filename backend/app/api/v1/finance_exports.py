"""Phase 5B — finance exports, account mappings and Moadian e-invoices API.

  /api/v1/admin/finance-exports            POST create (platform|seller|organization), GET list
  /api/v1/admin/finance-exports/<id>       GET metadata;  …/<id>/download  GET file
  /api/v1/admin/finance-formats            GET connectors + layouts
  /api/v1/admin/finance-mappings           GET list, POST upsert;  …/<id> DELETE
  /api/v1/admin/moadian/fiscal-ids         PUT issuer fiscal-memory id
  /api/v1/admin/moadian/preview            POST {source_ref} → payload (not stored)
  /api/v1/admin/moadian/documents          POST build (idempotent), GET list
  /api/v1/admin/moadian/documents/<id>     GET;  …/<id>/mark-submitted  POST
  /api/v1/supplier/finance-exports         POST/GET — the caller's own seller only
  /api/v1/supplier/finance-exports/<id>/download
  /api/v1/supplier/moadian/documents       GET — its own seller-issued invoices
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from app.adapters.accounting.finance_formats import list_finance_formats
from app.core.deps import current_user, get_db, require_auth
from app.core.errors import PermissionError_, ValidationError
from app.services import finance_export_service as fx
from app.services import moadian_invoice_service as moadian
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("finance_exports", __name__)


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d


def _int(v, field):
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not str(v).isdigit():
        raise ValidationError(f"{field} نامعتبر است")
    return int(v)


def _my_supplier(conn) -> int:
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب فروشنده برای این کاربر یافت نشد")
    return sid


def _download(job) -> Response:
    return Response(job["content"].encode("utf-8"), mimetype=job["content_type"].split(";")[0],
                    headers={"Content-Disposition": f'attachment; filename="{job["file_name"]}"',
                             "Content-Type": job["content_type"], "X-Content-SHA256": job["content_sha256"]})


# ───────────────────────────────────────────────────────────── admin exports
@bp.route("/api/v1/admin/finance-formats", methods=["GET"])
@require_auth("admin")
def formats():
    return jsonify({"formats": list_finance_formats()})


@bp.route("/api/v1/admin/finance-exports", methods=["POST"])
@require_auth("admin")
def admin_create_export():
    d = _body()
    entity_type = d.get("entity_type") or "platform"
    with get_db().write_transaction() as conn:
        job = fx.create_export_job(conn, entity_type=entity_type, entity_id=_int(d.get("entity_id"), "entity_id"),
                                   period_start=d.get("period_start"), period_end=d.get("period_end"),
                                   connector=d.get("connector") or "JSON", layout=d.get("layout"),
                                   user_id=current_user()["id"])
    return jsonify({"job": job}), (200 if job["reused"] else 201)


@bp.route("/api/v1/admin/finance-exports", methods=["GET"])
@require_auth("admin")
def admin_list_exports():
    with get_db().read_transaction() as conn:
        jobs = fx.list_jobs(conn, entity_type=request.args.get("entity_type") or None,
                            entity_id=_int(request.args.get("entity_id"), "entity_id"))
    return jsonify({"jobs": jobs})


@bp.route("/api/v1/admin/finance-exports/<int:job_id>", methods=["GET"])
@require_auth("admin")
def admin_get_export(job_id):
    with get_db().read_transaction() as conn:
        return jsonify({"job": fx.get_job(conn, job_id)})


@bp.route("/api/v1/admin/finance-exports/<int:job_id>/download", methods=["GET"])
@require_auth("admin")
def admin_download_export(job_id):
    with get_db().read_transaction() as conn:
        return _download(fx.get_job(conn, job_id, with_content=True))


# ───────────────────────────────────────────────────────────── mappings
@bp.route("/api/v1/admin/finance-mappings", methods=["GET"])
@require_auth("admin")
def list_mappings():
    with get_db().read_transaction() as conn:
        return jsonify({"mappings": fx.list_mappings(conn, request.args.get("connector") or None),
                        "account_keys": list(fx.ACCOUNT_KEYS)})


@bp.route("/api/v1/admin/finance-mappings", methods=["POST", "PUT"])
@require_auth("admin")
def upsert_mapping():
    with get_db().write_transaction() as conn:
        return jsonify({"mapping": fx.upsert_mapping(conn, _body())})


@bp.route("/api/v1/admin/finance-mappings/<int:mapping_id>", methods=["DELETE"])
@require_auth("admin")
def delete_mapping(mapping_id):
    with get_db().write_transaction() as conn:
        fx.delete_mapping(conn, mapping_id)
    return jsonify({"deleted": True})


# ───────────────────────────────────────────────────────────── moadian
@bp.route("/api/v1/admin/moadian/fiscal-ids", methods=["PUT", "POST"])
@require_auth("admin")
def set_fiscal_id():
    d = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"fiscal_id": moadian.set_fiscal_id(
            conn, issuer_key=str(d.get("issuer_key") or ""), fiscal_memory_id=str(d.get("fiscal_memory_id") or ""),
            economic_code=str(d.get("economic_code") or ""))})


@bp.route("/api/v1/admin/moadian/preview", methods=["POST"])
@require_auth("admin")
def moadian_preview():
    with get_db().read_transaction() as conn:
        return jsonify(moadian.preview(conn, str(_body().get("source_ref") or "")))


@bp.route("/api/v1/admin/moadian/documents", methods=["POST"])
@require_auth("admin")
def moadian_build():
    with get_db().write_transaction() as conn:
        doc = moadian.build_document(conn, str(_body().get("source_ref") or ""))
    return jsonify({"document": doc}), (200 if doc["reused"] else 201)


@bp.route("/api/v1/admin/moadian/documents", methods=["GET"])
@require_auth("admin")
def moadian_list():
    with get_db().read_transaction() as conn:
        return jsonify({"documents": moadian.list_documents(
            conn, issuer_type=request.args.get("issuer_type") or None,
            supplier_id=_int(request.args.get("supplier_id"), "supplier_id"),
            status=request.args.get("status") or None)})


@bp.route("/api/v1/admin/moadian/documents/<int:doc_id>", methods=["GET"])
@require_auth("admin")
def moadian_get(doc_id):
    with get_db().read_transaction() as conn:
        return jsonify({"document": moadian.get_document(conn, doc_id)})


@bp.route("/api/v1/admin/moadian/documents/<int:doc_id>/mark-submitted", methods=["POST"])
@require_auth("admin")
def moadian_mark(doc_id):
    d = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"document": moadian.mark_submitted(
            conn, doc_id, reference=d.get("reference"), status=d.get("status") or "submitted",
            error=d.get("error"))})


# ───────────────────────────────────────────────────────────── supplier (own data only)
@bp.route("/api/v1/supplier/finance-exports", methods=["POST"])
@require_auth()
def supplier_create_export():
    d = _body()
    with get_db().write_transaction() as conn:
        job = fx.create_export_job(conn, entity_type="seller", entity_id=_my_supplier(conn),
                                   period_start=d.get("period_start"), period_end=d.get("period_end"),
                                   connector=d.get("connector") or "JSON", layout=d.get("layout"),
                                   user_id=current_user()["id"])
    return jsonify({"job": job}), (200 if job["reused"] else 201)


@bp.route("/api/v1/supplier/finance-exports", methods=["GET"])
@require_auth()
def supplier_list_exports():
    with get_db().read_transaction() as conn:
        return jsonify({"jobs": fx.list_jobs(conn, entity_type="seller", entity_id=_my_supplier(conn))})


@bp.route("/api/v1/supplier/finance-exports/<int:job_id>/download", methods=["GET"])
@require_auth()
def supplier_download_export(job_id):
    with get_db().read_transaction() as conn:
        return _download(fx.get_job(conn, job_id, supplier_id=_my_supplier(conn), with_content=True))


@bp.route("/api/v1/supplier/moadian/documents", methods=["GET"])
@require_auth()
def supplier_moadian_list():
    with get_db().read_transaction() as conn:
        return jsonify({"documents": moadian.list_documents(conn, issuer_type="seller",
                                                            supplier_id=_my_supplier(conn))})
