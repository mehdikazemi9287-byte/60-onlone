"""Phase 5C logistics API (blueprint ``logistics_v2``).

  POST /api/v1/shipping/quote                       public  buyer-facing (no internal cost)
  GET  /api/v1/supplier/shipments                   supplier: own shipments
  POST /api/v1/supplier/shipments                   supplier: label for own FO
  POST /api/v1/supplier/shipments/<id>/pickup       supplier: pickup request for own shipment
  GET/POST /api/v1/admin/carriers/tariffs           admin
  PUT/DELETE /api/v1/admin/carriers/tariffs/<id>    admin (DELETE = deactivate)
  GET  /api/v1/me/orders/<order_id>/tracking        owner customer
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from app.core.deps import get_db, require_auth
from app.core.errors import NotFoundError, ValidationError
from app.services import fulfillment_service, shipment_orchestrator, shipping_rate_service

bp = Blueprint("logistics_v2", __name__)


def _body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد", code="invalid_body")
    return data


def _supplier_id(conn) -> int:
    sup = fulfillment_service.get_supplier_for_user(conn, g.current_user["id"])
    if sup is None:
        raise NotFoundError("حساب فروشنده یافت نشد", code="supplier_not_linked")
    return int(sup["id"])


def _origin_from_items(conn, parcels: list) -> dict | None:
    for p in parcels:
        if isinstance(p, dict) and p.get("product_id") is not None:
            q = ("SELECT sl.province, sl.city FROM seller_offers so JOIN supplier_locations sl "
                 "ON sl.id = so.supplier_location_id WHERE so.product_id = ? AND so.status = 'active'")
            args: list = [p["product_id"]]
            if p.get("seller_offer_id"):
                q += " AND so.id = ?"
                args.append(p["seller_offer_id"])
            row = conn.execute(q + " ORDER BY so.selling_price_minor LIMIT 1", args).fetchone()
            if row:
                return {"province": row["province"], "city": row["city"]}
    return None


@bp.route("/api/v1/shipping/quote", methods=["POST"])
def shipping_quote():
    data = _body()
    parcels = data.get("parcels") or data.get("items") or []
    with get_db().read_transaction() as conn:
        origin = data.get("origin") or _origin_from_items(conn, parcels if isinstance(parcels, list) else [])
        result = shipping_rate_service.quote_shipping(
            conn, origin, data.get("destination"), parcels,
            cod_value_minor=data.get("cod_value_minor", 0) or 0,
            insurance_value_minor=data.get("insurance_value_minor", 0) or 0,
            service_levels=data.get("service_levels"), strategy=data.get("strategy", "cheapest"),
        )
    return jsonify({
        "strategy": result["strategy"],
        "selected": shipping_rate_service.public_option(result["selected"]),
        "options": [shipping_rate_service.public_option(o) for o in result["options"]],
    }), 200


@bp.route("/api/v1/supplier/shipments", methods=["GET"])
@require_auth("supplier")
def supplier_shipments():
    with get_db().read_transaction() as conn:
        return jsonify({"shipments": shipment_orchestrator.list_supplier_shipments(conn, _supplier_id(conn))})


@bp.route("/api/v1/supplier/shipments", methods=["POST"])
@require_auth("supplier")
def supplier_create_shipment():
    data = _body()
    fo_id = data.get("fulfillment_order_id")
    if isinstance(fo_id, bool) or not isinstance(fo_id, int):
        raise ValidationError("شناسه سفارش تأمین الزامی است", code="fo_required")
    with get_db().write_transaction() as conn:
        sid = _supplier_id(conn)
        shipment = shipment_orchestrator.create_shipment_for_fo(
            conn, fo_id, supplier_id=sid, strategy=data.get("strategy", "cheapest"),
            service_level=data.get("service_level"), provider_code=data.get("provider_code"),
            cod=bool(data.get("cod")),
        )
        pickup = data.get("pickup")
        if isinstance(pickup, dict) and shipment["status"] == "created" and not shipment["pickup_requested_at"]:
            shipment = shipment_orchestrator.request_pickup(
                conn, shipment["id"], supplier_id=sid,
                window_start=pickup.get("window_start"), window_end=pickup.get("window_end"))
    return jsonify({"shipment": shipment}), 201


@bp.route("/api/v1/supplier/shipments/<int:shipment_id>/pickup", methods=["POST"])
@require_auth("supplier")
def supplier_pickup(shipment_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        shipment = shipment_orchestrator.request_pickup(
            conn, shipment_id, supplier_id=_supplier_id(conn),
            window_start=data.get("window_start"), window_end=data.get("window_end"))
    return jsonify({"shipment": shipment}), 200


@bp.route("/api/v1/admin/carriers/tariffs", methods=["GET"])
@require_auth("admin")
def admin_list_tariffs():
    with get_db().read_transaction() as conn:
        return jsonify({"tariffs": shipping_rate_service.list_tariffs(conn)})


@bp.route("/api/v1/admin/carriers/tariffs", methods=["POST"])
@require_auth("admin")
def admin_create_tariff():
    data = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"tariff": shipping_rate_service.create_tariff(conn, data)}), 201


@bp.route("/api/v1/admin/carriers/tariffs/<int:tariff_id>", methods=["PUT", "PATCH"])
@require_auth("admin")
def admin_update_tariff(tariff_id: int):
    data = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"tariff": shipping_rate_service.update_tariff(conn, tariff_id, data)})


@bp.route("/api/v1/admin/carriers/tariffs/<int:tariff_id>", methods=["DELETE"])
@require_auth("admin")
def admin_delete_tariff(tariff_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"tariff": shipping_rate_service.deactivate_tariff(conn, tariff_id)})


@bp.route("/api/v1/me/orders/<int:order_id>/tracking", methods=["GET"])
@require_auth("customer")
def my_order_tracking(order_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(shipment_orchestrator.get_order_tracking(conn, order_id, user_id=g.current_user["id"]))
