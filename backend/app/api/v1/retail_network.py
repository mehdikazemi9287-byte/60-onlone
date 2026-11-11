"""Retail network (شبکهٔ فروشگاه‌های زنجیره‌ای و طرف قرارداد): public map/coverage API and admin management.

Public endpoints only ever return branches of chains with an active contract (see retail_network_service._PUBLIC).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import client_ip, current_user, get_db, require_auth, require_org_role
from app.core.errors import ValidationError
from app.services import audit_service
from app.services import retail_network_service as svc

bp = Blueprint("retail_network", __name__, url_prefix="/api/v1")

MAX_CSV_BYTES = 2 * 1024 * 1024


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d


def _limit(default: int) -> int:
    try:
        return int(request.args.get("limit", default))
    except ValueError:
        raise ValidationError("«limit» باید عدد باشد") from None


def _audit(conn, action: str, entity_type: str, entity_id, metadata: dict | None = None) -> None:
    audit_service.record(conn, action=action, entity_type=entity_type, entity_id=entity_id,
                         actor_user_id=current_user()["id"], metadata=metadata or {}, ip_address=client_ip())


# ---------------------------------------------------------------- public

@bp.get("/network")
def network():
    a = request.args
    with get_db().read_transaction() as conn:
        return jsonify(svc.public_network(conn, province=a.get("province"), sector=a.get("sector"),
                                          chain=a.get("chain"), city=a.get("city"), limit=_limit(500)))


@bp.get("/network/coverage")
def coverage():
    with get_db().read_transaction() as conn:
        return jsonify(svc.public_coverage(conn, sector=request.args.get("sector")))


@bp.get("/network/sectors")
def sectors():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.list_sectors(conn)})


@bp.get("/network/chains")
def chains():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.public_chains(conn, sector=request.args.get("sector"))})


@bp.get("/network/chains/<slug>")
def chain(slug: str):
    with get_db().read_transaction() as conn:
        return jsonify(svc.public_chain(conn, slug))


@bp.get("/network/provinces/<slug>")
def province(slug: str):
    with get_db().read_transaction() as conn:
        return jsonify(svc.public_province(conn, slug))


# ---------------------------------------------------------------- admin

@bp.get("/admin/network/sectors")
@require_auth("admin")
def admin_sectors():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.list_sectors(conn, include_inactive=True)})


@bp.post("/admin/network/sectors")
@require_auth("admin")
def admin_create_sector():
    with get_db().write_transaction() as conn:
        out = svc.create_sector(conn, _body())
        _audit(conn, "network.sector.create", "chain_sector", out["id"], {"slug": out["slug"]})
        return jsonify(out), 201


@bp.put("/admin/network/sectors/<int:sector_id>")
@require_auth("admin")
def admin_toggle_sector(sector_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        svc.set_sector_active(conn, sector_id, d.get("active"))
        _audit(conn, "network.sector.update", "chain_sector", sector_id, {"active": d.get("active")})
        return jsonify({"ok": True})


@bp.get("/admin/network/chains")
@require_auth("admin")
def admin_chains():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.admin_list_chains(conn, status=request.args.get("status"),
                                                       q=request.args.get("q"))})


@bp.post("/admin/network/chains")
@require_auth("admin")
def admin_create_chain():
    with get_db().write_transaction() as conn:
        out = svc.create_chain(conn, _body(), actor_user_id=current_user()["id"])
        _audit(conn, "network.chain.create", "retail_chain", out["id"],
               {"slug": out["slug"], "contract_status": out["contract_status"]})
        return jsonify(out), 201


@bp.put("/admin/network/chains/<int:chain_id>")
@require_auth("admin")
def admin_update_chain(chain_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        out = svc.update_chain(conn, chain_id, d)
        _audit(conn, "network.chain.update", "retail_chain", chain_id, {"fields": sorted(d)})
        return jsonify(out)


@bp.get("/admin/network/branches")
@require_auth("admin")
def admin_branches():
    a = request.args
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.admin_list_branches(conn, chain=a.get("chain"), province=a.get("province"),
                                                         status=a.get("status"), limit=_limit(500))})


@bp.post("/admin/network/branches")
@require_auth("admin")
def admin_create_branch():
    with get_db().write_transaction() as conn:
        out = svc.create_branch(conn, _body())
        _audit(conn, "network.branch.create", "chain_branch", out["id"],
               {"chain": out["chain"]["slug"], "data_source": out["data_source"]})
        return jsonify(out), 201


@bp.put("/admin/network/branches/<int:branch_id>")
@require_auth("admin")
def admin_update_branch(branch_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        out = svc.update_branch(conn, branch_id, d)
        _audit(conn, "network.branch.update", "chain_branch", branch_id, {"fields": sorted(d)})
        return jsonify(out)


@bp.get("/admin/network/branches/template.csv")
@require_auth("admin")
def admin_csv_template():
    body = "﻿" + ",".join(svc.CSV_COLUMNS) + "\n"
    return body, 200, {"Content-Type": "text/csv; charset=utf-8",
                       "Content-Disposition": "attachment; filename=network-branches-template.csv"}


@bp.post("/admin/network/branches/import")
@require_auth("admin")
def admin_import():
    """multipart `file` or JSON {"csv": "..."}; `?commit=1` writes, otherwise a dry run that writes nothing."""
    commit = request.args.get("commit") in ("1", "true")
    if "file" in request.files:
        raw = request.files["file"].read(MAX_CSV_BYTES + 1)
        if len(raw) > MAX_CSV_BYTES:
            raise ValidationError("حداکثر حجم فایل ۲ مگابایت است", code="file_too_large")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValidationError("فایل باید CSV با کدگذاری UTF-8 باشد", code="bad_encoding") from None
    else:
        text = _body().get("csv")
        if isinstance(text, str) and len(text.encode()) > MAX_CSV_BYTES:
            raise ValidationError("حداکثر حجم فایل ۲ مگابایت است", code="file_too_large")
    with get_db().write_transaction() as conn:
        out = svc.import_branches_csv(conn, text, commit=commit)
        if commit:
            _audit(conn, "network.branch.import", "chain_branch", None,
                   {"created": out["created"], "updated": out["updated"], "errors": out["errors"]})
        return jsonify(out)


@bp.post("/admin/network/chains/<int:chain_id>/sync-locations")
@require_auth("admin")
def admin_sync_locations(chain_id: int):
    with get_db().write_transaction() as conn:
        out = svc.sync_chain_locations(conn, chain_id)
        _audit(conn, "network.chain.sync_locations", "retail_chain", chain_id,
               {"created": len(out["created"]), "supplier_id": out["supplier_id"]})
        return jsonify(out)


# ---------------------------------------------------------------- organization panel

@bp.get("/organizations/<int:org_id>/network-coverage")
@require_org_role("organization_admin")
def org_coverage(org_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(svc.organization_coverage(conn, org_id))
