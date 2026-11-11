"""Tiered Vambi price alerts — every user sees only their OWN level's price (see price_alert_service).

GET    /api/v1/me/price-watches[?product=<slug>]   my watches (optionally one product: the button's state check)
GET    /api/v1/me/price-watches/level              my detected level (for the «زیر نظر بگیر» button)
POST   /api/v1/me/price-watches                    {slug|product_id, target_price_minor?, quantity?, alert_types?,
                                                    organization_id?, sms_enabled?}  → 201 new / 200 updated
PATCH  /api/v1/me/price-watches/<id>               {target_price_minor?, quantity?, alert_types?, active?, sms_enabled?}
DELETE /api/v1/me/price-watches/<id>
GET    /api/v1/me/price-watches/<id>/history?days= daily price at my level, up to 90 days
GET    /api/v1/supplier/price-alerts               seller panel: own best-offer status + recent alerts (no competitor price)
PATCH  /api/v1/supplier/price-alerts/settings      {sms_enabled: bool} the seller's own SMS for these alerts

The level is computed on the server from the account; organization_id only selects among the caller's own
active memberships. Watches are owner-only (404 for anyone else's id).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import PermissionError_, ValidationError
from app.services import price_alert_service as svc
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("price_alerts", __name__, url_prefix="/api/v1")


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    return data


@bp.get("/me/price-watches")
@require_auth()
def list_watches():
    with get_db().read_transaction() as conn:
        return jsonify(svc.list_watches(conn, current_user(), request.args.get("product")))


@bp.get("/me/price-watches/level")
@require_auth()
def my_level():
    with get_db().read_transaction() as conn:
        return jsonify(svc.level_options(conn, current_user()))


@bp.post("/me/price-watches")
@require_auth()
def create_watch():
    data = _body()
    with get_db().write_transaction() as conn:
        watch, created = svc.create_watch(conn, current_user(), data)
    return jsonify({"watch": watch}), (201 if created else 200)


@bp.patch("/me/price-watches/<int:watch_id>")
@require_auth()
def update_watch(watch_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"watch": svc.update_watch(conn, current_user(), watch_id, data)})


@bp.delete("/me/price-watches/<int:watch_id>")
@require_auth()
def delete_watch(watch_id: int):
    with get_db().write_transaction() as conn:
        svc.delete_watch(conn, current_user(), watch_id)
    return jsonify({"deleted": True})


@bp.get("/me/price-watches/<int:watch_id>/history")
@require_auth()
def watch_history(watch_id: int):
    try:
        days = int(request.args.get("days", svc.HISTORY_DAYS))
    except ValueError:
        raise ValidationError("days نامعتبر است") from None
    with get_db().read_transaction() as conn:
        return jsonify(svc.history(conn, current_user(), watch_id, days))


@bp.get("/supplier/price-alerts")
@require_auth()
def seller_alerts():
    with get_db().read_transaction() as conn:
        sid = current_supplier_id(conn, current_user()["id"])
        if not sid:
            raise PermissionError_("حساب فروشنده یافت نشد")
        return jsonify(svc.seller_alerts(conn, sid, current_user()["id"]))


@bp.patch("/supplier/price-alerts/settings")
@require_auth()
def seller_alert_settings():
    data = _body()
    with get_db().write_transaction() as conn:
        if not current_supplier_id(conn, current_user()["id"]):
            raise PermissionError_("حساب فروشنده یافت نشد")
        return jsonify(svc.set_seller_sms(conn, current_user()["id"], data.get("sms_enabled")))
