"""Public partner web services: /api/partner/v1 (X-Api-Key auth, cursor pagination).

Error envelope is the main API's: {"error": {"code", "message", "details"?}}.
List envelope: {"data": [...], "next_cursor": "<opaque>|null"}.
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from app.core.api_keys import require_api_key
from app.core.errors import ValidationError
from app.services import partner_api_service as svc

bp = Blueprint("partner_v1", __name__, url_prefix="/api/partner/v1")


def _db():
    return current_app.extensions["db"]


def _master_key() -> str:
    return current_app.extensions["settings"].secret_key


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("بدنه JSON نامعتبر است", code="invalid_json")
    return body


@bp.after_request
def _headers(response):
    response.headers["Cache-Control"] = "no-store"
    retry = getattr(g, "partner_retry_after", None)
    if retry is not None:
        response.headers["Retry-After"] = str(max(int(retry), 1))
    return response


@bp.get("/openapi.json")
def openapi():
    return jsonify(OPENAPI)


@bp.get("/me")
@require_api_key()
def me():
    c = g.partner
    return jsonify({"client": {"id": c["client_id"], "name": c["name"], "owner_type": c["owner_type"],
                               "organization_id": c["organization_id"], "supplier_id": c["supplier_id"],
                               "scopes": c["scopes"], "rate_limit_per_minute": c["rate_limit_per_minute"],
                               "key_prefix": c["prefix"]}})


@bp.get("/catalog/products")
@require_api_key("catalog:read")
def catalog_products():
    with _db().read_transaction() as conn:
        return jsonify(svc.catalog_products(conn, cursor=request.args.get("cursor"), limit=svc.page_limit(request.args.get("limit"))))


@bp.get("/catalog/offers")
@require_api_key("catalog:read")
def catalog_offers():
    pid = request.args.get("product_id")
    if pid is not None and not pid.isdigit():
        raise ValidationError("product_id نامعتبر است")
    with _db().read_transaction() as conn:
        return jsonify(svc.catalog_offers(conn, product_id=int(pid) if pid else None, cursor=request.args.get("cursor"),
                                          limit=svc.page_limit(request.args.get("limit"))))


@bp.get("/offers")
@require_api_key("offers:write")
def my_offers():
    with _db().read_transaction() as conn:
        return jsonify(svc.list_own_offers(conn, client=g.partner, cursor=request.args.get("cursor"),
                                           limit=svc.page_limit(request.args.get("limit"))))


@bp.put("/offers")
@require_api_key("offers:write")
def upsert_offer():
    body = _json_body()
    with _db().write_transaction() as conn:
        offer, created = svc.upsert_offer(conn, client=g.partner, data=body)
    return jsonify({"offer": offer, "created": created}), 201 if created else 200


@bp.get("/orders")
@require_api_key("orders:read")
def orders():
    with _db().read_transaction() as conn:
        return jsonify(svc.list_orders(conn, client=g.partner, cursor=request.args.get("cursor"),
                                       limit=svc.page_limit(request.args.get("limit"))))


@bp.get("/orders/<order_number>")
@require_api_key("orders:read")
def order_detail(order_number: str):
    from app.core.errors import NotFoundError
    with _db().read_transaction() as conn:
        page = svc.list_orders(conn, client=g.partner, cursor=None, limit=100, order_number=order_number[:64])
    if not page["data"]:
        raise NotFoundError("سفارش یافت نشد")
    return jsonify({"order": page["data"][0] if len(page["data"]) == 1 else None, "data": page["data"]})


@bp.post("/shipments/<int:shipment_id>/status")
@require_api_key("shipments:write")
def shipment_status(shipment_id: int):
    body = _json_body()
    with _db().write_transaction() as conn:
        result = svc.update_shipment_status(conn, client=g.partner, shipment_id=shipment_id,
                                            status=body.get("status"), reason=body.get("reason"))
    return jsonify({"shipment": result})


@bp.get("/credit/balance")
@require_api_key("credit:read")
def credit_balance():
    with _db().read_transaction() as conn:
        return jsonify({"balance": svc.credit_balance(conn, client=g.partner)})


@bp.get("/inbound")
@require_api_key()
def inbound_sources():
    return jsonify({"data": [{"source": k, "scope": v["scope"], "description": v["description"]}
                             for k, v in sorted(svc.INBOUND_HANDLERS.items())]})


@bp.post("/inbound/<source>")
@require_api_key()
def inbound(source: str):
    status, body = svc.process_inbound(
        _db(), client=g.partner, source=source[:64], idempotency_key=request.headers.get("Idempotency-Key"),
        raw_body=request.get_data(cache=True), signature_header=request.headers.get("X-60Online-Signature"),
        master_key=_master_key())
    return jsonify(body), status


# --------------------------------------------------------------- OpenAPI 3.1
def _list_of(ref: str) -> dict:
    return {"type": "object", "properties": {"data": {"type": "array", "items": {"$ref": ref}},
                                             "next_cursor": {"type": ["string", "null"]}}}


def _op(summary: str, scope: str | None, response: dict, *, params=(), body: str | None = None, ok: str = "200") -> dict:
    op = {"summary": summary, "security": [{"ApiKey": []}],
          "parameters": [{"$ref": f"#/components/parameters/{p}"} for p in params],
          "responses": {ok: {"description": "OK", "content": {"application/json": {"schema": response}}},
                        "401": {"$ref": "#/components/responses/Error"}, "403": {"$ref": "#/components/responses/Error"},
                        "422": {"$ref": "#/components/responses/Error"}, "429": {"$ref": "#/components/responses/Error"}}}
    if scope:
        op["x-required-scope"] = scope
    if body:
        op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"$ref": body}}}}
    return op


_OBJ = {"type": "object"}
OPENAPI: dict = {
    "openapi": "3.1.0",
    "info": {"title": "60Online Partner API", "version": "1.0.0",
             "description": "وب‌سرویس شرکای ۶۰آنلاین. مبالغ به ریال صحیح (*_minor). احراز هویت با X-Api-Key: <prefix>.<secret>."},
    "servers": [{"url": "/api/partner/v1"}],
    "components": {
        "securitySchemes": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}},
        "parameters": {
            "cursor": {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            "limit": {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}},
            "product_id": {"name": "product_id", "in": "query", "schema": {"type": "integer"}},
            "signature": {"name": "X-60Online-Signature", "in": "header", "required": True,
                          "schema": {"type": "string", "example": "t=1700000000,v1=<hex>"}},
            "idempotency": {"name": "Idempotency-Key", "in": "header", "required": True,
                            "schema": {"type": "string", "minLength": 8, "maxLength": 120}},
        },
        "responses": {"Error": {"description": "Error envelope", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}},
        "schemas": {
            "Error": {"type": "object", "required": ["error"], "properties": {"error": {
                "type": "object", "required": ["code", "message"],
                "properties": {"code": {"type": "string"}, "message": {"type": "string"}, "details": _OBJ}}}},
            "Product": {"type": "object", "properties": {
                "id": {"type": "integer"}, "slug": {"type": "string"}, "sku": {"type": "string"}, "title_fa": {"type": "string"},
                "base_price_minor": {"type": "integer"}, "best_price_minor": {"type": ["integer", "null"]},
                "available_stock": {"type": "integer"}, "offer_count": {"type": "integer"}}},
            "Offer": {"type": "object", "properties": {
                "id": {"type": "integer"}, "product_id": {"type": "integer"}, "supplier_id": {"type": "integer"},
                "supplier_location_id": {"type": "integer"}, "supplier_sku": {"type": ["string", "null"]},
                "selling_price_minor": {"type": "integer"}, "available_stock": {"type": "integer"},
                "stock_quantity": {"type": "integer"}, "status": {"type": "string"}, "pricing_mode": {"type": "string"},
                "channel": {"type": "string"}}},
            "OfferUpsert": {"type": "object", "required": ["product_id"], "properties": {
                "product_id": {"type": "integer"}, "supplier_location_id": {"type": "integer"},
                "selling_price_minor": {"type": "integer"}, "stock_quantity": {"type": "integer"},
                "supplier_sku": {"type": "string"}, "pricing_mode": {"type": "string"}, "channel": {"type": "string"},
                "min_order_quantity": {"type": "integer"}, "lead_time_days": {"type": "integer"}}},
            "Order": _OBJ,
            "ShipmentStatus": {"type": "object", "required": ["status"], "properties": {
                "status": {"enum": ["in_transit", "out_for_delivery", "delivered", "failed", "returned"]},
                "reason": {"type": "string"}}},
            "WebhookEvent": {"type": "object", "properties": {
                "id": {"type": "string"}, "created_at": {"type": "string"}, "data": _OBJ,
                "type": {"enum": ["order.created", "order.status_changed", "offer.stock_low",
                                  "settlement.completed", "credit.statement_issued"]}}},
        },
    },
    "paths": {
        "/me": {"get": _op("کلید جاری و مجوزها", None, _OBJ)},
        "/catalog/products": {"get": _op("کاتالوگ کالا با بهترین قیمت و موجودی", "catalog:read",
                                         _list_of("#/components/schemas/Product"), params=("cursor", "limit"))},
        "/catalog/offers": {"get": _op("پیشنهادهای فعال", "catalog:read", _list_of("#/components/schemas/Offer"),
                                       params=("product_id", "cursor", "limit"))},
        "/offers": {"get": _op("پیشنهادهای خود تأمین‌کننده", "offers:write", _list_of("#/components/schemas/Offer"),
                               params=("cursor", "limit")),
                    "put": _op("ایجاد/به‌روزرسانی پیشنهاد خود", "offers:write", _OBJ,
                               body="#/components/schemas/OfferUpsert")},
        "/orders": {"get": _op("سفارش‌های تأمین‌کننده یا سازمان کلید", "orders:read",
                               _list_of("#/components/schemas/Order"), params=("cursor", "limit"))},
        "/orders/{order_number}": {"get": {**_op("جزئیات سفارش", "orders:read", _OBJ),
                                           "parameters": [{"name": "order_number", "in": "path", "required": True,
                                                           "schema": {"type": "string"}}]}},
        "/shipments/{shipment_id}/status": {"post": {**_op("تغییر وضعیت مرسوله", "shipments:write", _OBJ,
                                                           body="#/components/schemas/ShipmentStatus"),
                                                     "parameters": [{"name": "shipment_id", "in": "path", "required": True,
                                                                     "schema": {"type": "integer"}}]}},
        "/credit/balance": {"get": _op("مانده اعتبار سازمان", "credit:read", _OBJ)},
        "/inbound": {"get": _op("فهرست منابع ورودی ثبت‌شده", None, _OBJ)},
        "/inbound/{source}": {"post": {**_op("دریافت وب‌سرویس ورودی (HMAC + Idempotency-Key)", "per-source", _OBJ,
                                             params=("signature", "idempotency"), ok="201"),
                                       "requestBody": {"required": True, "content": {"application/json": {"schema": _OBJ}}},
                                       "x-sources": {"supplier.price_stock": "offers:write", "shipment.tracking": "shipments:write"}}},
        "/openapi.json": {"get": {"summary": "همین سند", "security": [], "responses": {"200": {"description": "OK"}}}},
    },
    "webhooks": {"partnerEvent": {"post": {
        "summary": "رویداد خروجی امضاشده با X-60Online-Signature: t=<ts>,v1=hmac_sha256(secret, t + '.' + body)",
        "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/WebhookEvent"}}}},
        "responses": {"200": {"description": "2xx = delivered; otherwise retried with exponential backoff"}}}}},
}
