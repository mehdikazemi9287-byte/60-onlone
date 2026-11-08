"""Partner API: client/key administration, partner read/write operations and the
inbound web-service registry. Amounts are integer Rial (``*_minor``)."""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Callable

from app.core import api_keys
from app.core.errors import ApiError, AuthenticationError, ConflictError, NotFoundError, PermissionError_, ValidationError

OWNER_TYPES = ("platform", "user", "organization", "supplier")
STOCK_LOW_THRESHOLD = 5


# ----------------------------------------------------------------------- audit
def audit(conn, *, actor_user_id: int | None, action: str, entity_type: str, entity_id, metadata: dict | None = None,
          ip: str | None = None) -> None:
    conn.execute("INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id, metadata_json, ip_address) VALUES (?,?,?,?,?,?)",
                 (actor_user_id, action, entity_type, None if entity_id is None else str(entity_id),
                  json.dumps(metadata or {}, ensure_ascii=False, default=str), ip))


# -------------------------------------------------------------------- helpers
def _int(v, field: str, lo: int = 1, hi: int = 10**13, optional: bool = False):
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValidationError(f"{field} نامعتبر است", details={"field": field})
    return v


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(f"id:{int(last_id)}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not raw.startswith("id:"):
            raise ValueError
        value = int(raw[3:])
        if value < 0:
            raise ValueError
        return value
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("مقدار cursor نامعتبر است", code="invalid_cursor")


def page_limit(raw) -> int:
    if raw in (None, ""):
        return 50
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError("مقدار limit نامعتبر است")
    if not 1 <= value <= 100:
        raise ValidationError("مقدار limit باید بین ۱ تا ۱۰۰ باشد")
    return value


def _page(rows: list, limit: int, mapper: Callable) -> dict:
    more = len(rows) > limit
    rows = rows[:limit]
    return {"data": [mapper(r) for r in rows],
            "next_cursor": encode_cursor(rows[-1]["id"]) if more and rows else None}


# ---------------------------------------------------------- client administration
def _clean_scopes(raw) -> list[str]:
    if not isinstance(raw, list) or any(s not in api_keys.SCOPES for s in raw):
        raise ValidationError("فهرست مجوزها نامعتبر است", details={"allowed": list(api_keys.SCOPES)})
    return sorted(set(raw))


def client_dict(conn, row) -> dict:
    d = dict(row)
    d["scopes"] = json.loads(d.pop("scopes_json") or "[]")
    d.pop("signing_salt", None)
    d["keys"] = [dict(k) for k in conn.execute(
        "SELECT id, prefix, status, rotated_from_id, created_at, revoked_at, last_used_at FROM partner_api_keys WHERE client_id=? ORDER BY id",
        (row["id"],)).fetchall()]
    return d


def get_client(conn, client_id: int) -> dict:
    row = conn.execute("SELECT * FROM partner_api_clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise NotFoundError("مشتری API یافت نشد")
    return client_dict(conn, row)


def list_clients(conn) -> list[dict]:
    return [client_dict(conn, r) for r in conn.execute("SELECT * FROM partner_api_clients ORDER BY id DESC").fetchall()]


def create_client(conn, *, data: dict, actor_user_id: int, ip: str | None = None) -> dict:
    name = (data.get("name") or "").strip() if isinstance(data.get("name"), str) else ""
    if not 2 <= len(name) <= 120:
        raise ValidationError("نام مشتری API الزامی است")
    owner_type = data.get("owner_type", "supplier")
    if owner_type not in OWNER_TYPES:
        raise ValidationError("نوع مالک نامعتبر است")
    org = _int(data.get("organization_id"), "organization_id", optional=True)
    sup = _int(data.get("supplier_id"), "supplier_id", optional=True)
    user = _int(data.get("owner_user_id"), "owner_user_id", optional=True)
    if owner_type == "organization" and (org is None or not conn.execute("SELECT 1 FROM organizations WHERE id=?", (org,)).fetchone()):
        raise ValidationError("سازمان مالک یافت نشد")
    if owner_type == "supplier" and (sup is None or not conn.execute("SELECT 1 FROM suppliers WHERE id=?", (sup,)).fetchone()):
        raise ValidationError("تأمین‌کننده مالک یافت نشد")
    if owner_type == "user" and (user is None or not conn.execute("SELECT 1 FROM users WHERE id=?", (user,)).fetchone()):
        raise ValidationError("کاربر مالک یافت نشد")
    if owner_type != "organization":
        org = None
    if owner_type != "supplier":
        sup = None
    scopes = _clean_scopes(data.get("scopes", []))
    rate = _int(data.get("rate_limit_per_minute", 60), "rate_limit_per_minute", 1, 6000)
    stamp = api_keys.now_iso()
    cid = conn.execute(
        """INSERT INTO partner_api_clients (name, owner_type, owner_user_id, organization_id, supplier_id, scopes_json,
               rate_limit_per_minute, created_by_user_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (name, owner_type, user, org, sup, json.dumps(scopes), rate, actor_user_id, stamp, stamp)).lastrowid
    audit(conn, actor_user_id=actor_user_id, action="partner_client.created", entity_type="partner_api_client",
          entity_id=cid, metadata={"owner_type": owner_type, "scopes": scopes}, ip=ip)
    return get_client(conn, cid)


def update_client(conn, *, client_id: int, data: dict, actor_user_id: int, ip: str | None = None) -> dict:
    before = get_client(conn, client_id)
    scopes = _clean_scopes(data["scopes"]) if "scopes" in data else before["scopes"]
    rate = _int(data.get("rate_limit_per_minute", before["rate_limit_per_minute"]), "rate_limit_per_minute", 1, 6000)
    status = data.get("status", before["status"])
    if status not in ("active", "suspended", "revoked"):
        raise ValidationError("وضعیت نامعتبر است")
    if before["status"] == "revoked" and status != "revoked":
        raise ConflictError("مشتری باطل‌شده قابل فعال‌سازی نیست")
    name = data.get("name", before["name"])
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 120:
        raise ValidationError("نام مشتری API نامعتبر است")
    stamp = api_keys.now_iso()
    conn.execute("""UPDATE partner_api_clients SET name=?, scopes_json=?, rate_limit_per_minute=?, status=?, updated_at=?,
                    revoked_at=CASE WHEN ?='revoked' THEN COALESCE(revoked_at, ?) ELSE revoked_at END WHERE id=?""",
                 (name.strip(), json.dumps(scopes), rate, status, stamp, status, stamp, client_id))
    if status == "revoked":
        conn.execute("UPDATE partner_api_keys SET status='revoked', revoked_at=COALESCE(revoked_at, ?) WHERE client_id=?",
                     (stamp, client_id))
    audit(conn, actor_user_id=actor_user_id, action="partner_client.updated", entity_type="partner_api_client",
          entity_id=client_id, metadata={"scopes": scopes, "status": status, "rate_limit_per_minute": rate}, ip=ip)
    return get_client(conn, client_id)


def issue_key(conn, *, client_id: int, actor_user_id: int, rotated_from_id: int | None = None, ip: str | None = None) -> dict:
    client = get_client(conn, client_id)
    if client["status"] == "revoked":
        raise ConflictError("مشتری API باطل شده است")
    prefix, plaintext = api_keys.generate_key()
    secret = plaintext.split(".", 1)[1]
    kid = conn.execute(
        """INSERT INTO partner_api_keys (client_id, prefix, secret_hash, rotated_from_id, created_by_user_id, created_at)
           VALUES (?,?,?,?,?,?)""",
        (client_id, prefix, api_keys.hash_secret(secret), rotated_from_id, actor_user_id, api_keys.now_iso())).lastrowid
    audit(conn, actor_user_id=actor_user_id, action="partner_key.issued", entity_type="partner_api_key", entity_id=kid,
          metadata={"client_id": client_id, "prefix": prefix, "rotated_from_id": rotated_from_id}, ip=ip)
    return {"id": kid, "prefix": prefix, "api_key": plaintext,
            "notice": "این کلید فقط یک بار نمایش داده می‌شود؛ آن را امن نگه دارید."}


def _key(conn, client_id: int, key_id: int):
    row = conn.execute("SELECT * FROM partner_api_keys WHERE id=? AND client_id=?", (key_id, client_id)).fetchone()
    if not row:
        raise NotFoundError("کلید یافت نشد")
    return row


def revoke_key(conn, *, client_id: int, key_id: int, actor_user_id: int, ip: str | None = None) -> dict:
    _key(conn, client_id, key_id)
    conn.execute("UPDATE partner_api_keys SET status='revoked', revoked_at=COALESCE(revoked_at, ?) WHERE id=?",
                 (api_keys.now_iso(), key_id))
    audit(conn, actor_user_id=actor_user_id, action="partner_key.revoked", entity_type="partner_api_key", entity_id=key_id,
          metadata={"client_id": client_id}, ip=ip)
    return dict(conn.execute("SELECT id, prefix, status, revoked_at FROM partner_api_keys WHERE id=?", (key_id,)).fetchone())


def rotate_key(conn, *, client_id: int, key_id: int, actor_user_id: int, ip: str | None = None) -> dict:
    old = _key(conn, client_id, key_id)
    if old["status"] != "active":
        raise ConflictError("فقط کلید فعال قابل چرخش است")
    revoke_key(conn, client_id=client_id, key_id=key_id, actor_user_id=actor_user_id, ip=ip)
    return issue_key(conn, client_id=client_id, actor_user_id=actor_user_id, rotated_from_id=key_id, ip=ip)


def rotate_signing_secret(conn, *, client_id: int, master_key: str, actor_user_id: int, ip: str | None = None) -> dict:
    get_client(conn, client_id)
    salt = api_keys.new_salt()
    secret = api_keys.derive_signing_secret(master_key, salt)
    conn.execute("UPDATE partner_api_clients SET signing_salt=?, signing_fingerprint=?, updated_at=? WHERE id=?",
                 (salt, api_keys.fingerprint(secret), api_keys.now_iso(), client_id))
    audit(conn, actor_user_id=actor_user_id, action="partner_signing_secret.rotated", entity_type="partner_api_client",
          entity_id=client_id, metadata={"fingerprint": api_keys.fingerprint(secret)}, ip=ip)
    return {"signing_secret": secret, "fingerprint": api_keys.fingerprint(secret),
            "notice": "این کلید امضا فقط یک بار نمایش داده می‌شود."}


def list_inbound(conn, *, client_id: int, limit: int = 50) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT id, source, idempotency_key, status, error, result_json, created_at, processed_at
           FROM partner_inbound_messages WHERE client_id=? ORDER BY id DESC LIMIT ?""", (client_id, limit)).fetchall()]


# --------------------------------------------------------------- ownership guards
def require_supplier(client: dict) -> int:
    if client["owner_type"] != "supplier" or not client.get("supplier_id"):
        raise PermissionError_("این عملیات فقط برای کلید تأمین‌کننده مجاز است", code="supplier_key_required")
    return int(client["supplier_id"])


def require_organization(client: dict) -> int:
    if client["owner_type"] != "organization" or not client.get("organization_id"):
        raise PermissionError_("این عملیات فقط برای کلید سازمان مجاز است", code="organization_key_required")
    return int(client["organization_id"])


# ----------------------------------------------------------------------- catalog
def catalog_products(conn, *, cursor: str | None, limit: int) -> dict:
    after = decode_cursor(cursor)
    rows = conn.execute(
        """SELECT p.id, p.slug, p.sku, p.title_fa, p.brand_fa, p.base_price_minor, p.currency,
                  (SELECT MIN(so.selling_price_minor) FROM seller_offers so WHERE so.product_id=p.id AND so.status='active'
                       AND so.selling_price_minor > 0 AND so.stock_quantity - so.stock_reserved > 0) AS best_price_minor,
                  (SELECT COALESCE(SUM(so.stock_quantity - so.stock_reserved), 0) FROM seller_offers so
                       WHERE so.product_id=p.id AND so.status='active' AND so.stock_quantity > so.stock_reserved) AS available_stock,
                  (SELECT COUNT(*) FROM seller_offers so WHERE so.product_id=p.id AND so.status='active') AS offer_count
           FROM products p WHERE p.is_active=1 AND p.provenance='real' AND p.id > ? ORDER BY p.id LIMIT ?""",
        (after, limit + 1)).fetchall()
    return _page(rows, limit, lambda r: {**dict(r), "available_stock": int(r["available_stock"] or 0),
                                         "offer_count": int(r["offer_count"] or 0)})


def _offer_public(r) -> dict:
    return {"id": r["id"], "product_id": r["product_id"], "supplier_id": r["supplier_id"],
            "supplier_location_id": r["supplier_location_id"], "supplier_sku": r["supplier_sku"],
            "selling_price_minor": r["selling_price_minor"],
            "available_stock": max(int(r["stock_quantity"]) - int(r["stock_reserved"]), 0),
            "stock_quantity": r["stock_quantity"], "status": r["status"], "pricing_mode": r["pricing_mode"],
            "channel": r["channel"], "min_order_quantity": r["min_order_quantity"],
            "max_order_quantity": r["max_order_quantity"], "lead_time_days": r["lead_time_days"],
            "updated_at": r["updated_at"]}


def catalog_offers(conn, *, product_id: int | None, cursor: str | None, limit: int) -> dict:
    after = decode_cursor(cursor)
    sql = """SELECT so.* FROM seller_offers so JOIN products p ON p.id=so.product_id
             WHERE so.status='active' AND p.is_active=1 AND p.provenance='real' AND so.id > ?"""
    params: list = [after]
    if product_id is not None:
        sql += " AND so.product_id = ?"
        params.append(product_id)
    rows = conn.execute(sql + " ORDER BY so.id LIMIT ?", (*params, limit + 1)).fetchall()
    return _page(rows, limit, _offer_public)


def list_own_offers(conn, *, client: dict, cursor: str | None, limit: int) -> dict:
    supplier_id = require_supplier(client)
    rows = conn.execute("SELECT * FROM seller_offers WHERE supplier_id=? AND id > ? ORDER BY id LIMIT ?",
                        (supplier_id, decode_cursor(cursor), limit + 1)).fetchall()
    return _page(rows, limit, _offer_public)


def _actor_for(conn, client: dict) -> int | None:
    if client.get("owner_user_id"):
        return int(client["owner_user_id"])
    if client.get("supplier_id"):
        row = conn.execute("SELECT user_id FROM suppliers WHERE id=?", (client["supplier_id"],)).fetchone()
        return int(row["user_id"]) if row and row["user_id"] else None
    return None


_OFFER_FIELDS = ("pricing_mode", "channel", "selling_price_minor", "tiers", "stock_quantity", "min_order_quantity",
                 "max_order_quantity", "lead_time_days", "valid_until", "supplier_sku", "source_reference")


def upsert_offer(conn, *, client: dict, data: dict) -> tuple[dict, bool]:
    """Create or partially update the key's own offer for (product, location). Returns (offer, created)."""
    from app.services import marketplace_offer_service as offers

    supplier_id = require_supplier(client)
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست نامعتبر است")
    product_id = _int(data.get("product_id"), "product_id")
    loc = _int(data.get("supplier_location_id"), "supplier_location_id", optional=True)
    actor = _actor_for(conn, client)
    existing = conn.execute(
        "SELECT id FROM seller_offers WHERE product_id=? AND supplier_id=? AND supplier_location_id=? ORDER BY id LIMIT 1",
        (product_id, supplier_id, loc)).fetchone() if loc is not None else conn.execute(
        "SELECT id FROM seller_offers WHERE product_id=? AND supplier_id=? ORDER BY id LIMIT 1",
        (product_id, supplier_id)).fetchone()
    payload = {k: data[k] for k in _OFFER_FIELDS if k in data}
    payload["confirm"] = True
    if existing:
        snap = offers._snapshot(conn, existing["id"])
        merged = {k: snap.get(k) for k in _OFFER_FIELDS}
        merged.update(payload)
        result = offers.update(conn, supplier_id=supplier_id, offer_id=existing["id"], actor=actor, data=merged)
        created = False
    else:
        payload.update({"product_id": product_id, "supplier_location_id": loc})
        result = offers.create(conn, supplier_id=supplier_id, actor=actor, data=payload)
        created = True
    audit(conn, actor_user_id=actor, action="partner_offer.upserted", entity_type="seller_offer", entity_id=result["id"],
          metadata={"client_id": client["client_id"], "created": created})
    _maybe_stock_low(conn, result)
    row = conn.execute("SELECT * FROM seller_offers WHERE id=?", (result["id"],)).fetchone()
    return _offer_public(row), created


def _maybe_stock_low(conn, offer: dict) -> None:
    from app.services import partner_webhook_service as hooks

    available = int(offer["stock_quantity"]) - int(offer.get("stock_reserved") or 0)
    if available <= STOCK_LOW_THRESHOLD:
        hooks.emit(conn, "offer.stock_low",
                   {"offer_id": offer["id"], "product_id": offer["product_id"], "available_stock": max(available, 0),
                    "threshold": STOCK_LOW_THRESHOLD},
                   supplier_ids=[offer["supplier_id"]],
                   event_key=f"offer.stock_low:{offer['id']}:{offer.get('updated_at')}:{available}")


# ------------------------------------------------------------------------ orders
def _supplier_order(conn, r) -> dict:
    items = [dict(i) for i in conn.execute(
        """SELECT product_id, title_fa, quantity, selling_price_minor, line_selling_minor
           FROM fulfillment_order_items WHERE fulfillment_order_id=? ORDER BY id""", (r["id"],)).fetchall()]
    ship = conn.execute("SELECT id, status, tracking_code FROM shipments WHERE fulfillment_order_id=? ORDER BY id DESC LIMIT 1",
                        (r["id"],)).fetchone()
    return {"id": r["id"], "fulfillment_order_id": r["id"], "order_number": r["order_number"], "status": r["status"],
            "order_status": r["order_status"], "placed_at": r["placed_at"],
            "shipping": {"province": r["shipping_province"], "city": r["shipping_city"]},
            "items": items, "shipment": dict(ship) if ship else None}


def _org_order(conn, r) -> dict:
    items = [dict(i) for i in conn.execute(
        "SELECT product_id, quantity, unit_price_minor, line_total_minor FROM order_items WHERE order_id=? ORDER BY id",
        (r["id"],)).fetchall()] if _has_cols(conn, "order_items", ("unit_price_minor", "line_total_minor")) else []
    return {"id": r["id"], "order_number": r["order_number"], "status": r["status"], "placed_at": r["placed_at"],
            "subtotal_minor": r["subtotal_minor"], "shipping_fee_minor": r["shipping_fee_minor"],
            "total_minor": r["total_minor"], "currency": r["currency"], "items": items}


_COLS_CACHE: dict[tuple[str, tuple], bool] = {}


def _has_cols(conn, table: str, cols: tuple) -> bool:
    key = (table, cols)
    if key not in _COLS_CACHE:
        try:
            conn.execute(f"SELECT {', '.join(cols)} FROM {table} LIMIT 0").fetchall()
            _COLS_CACHE[key] = True
        except Exception:
            _COLS_CACHE[key] = False
    return _COLS_CACHE[key]


def list_orders(conn, *, client: dict, cursor: str | None, limit: int, order_number: str | None = None) -> dict:
    after = decode_cursor(cursor)
    if client["owner_type"] == "supplier" and client.get("supplier_id"):
        sql = """SELECT fo.id, fo.status, o.order_number, o.status AS order_status, o.placed_at, o.shipping_province, o.shipping_city
                 FROM fulfillment_orders fo JOIN orders o ON o.id=fo.order_id WHERE fo.supplier_id=? AND fo.id > ?"""
        params: list = [client["supplier_id"], after]
        mapper = lambda r: _supplier_order(conn, r)  # noqa: E731
    elif client["owner_type"] == "organization" and client.get("organization_id"):
        sql = "SELECT o.* FROM orders o WHERE o.organization_id=? AND o.id > ?"
        params = [client["organization_id"], after]
        mapper = lambda r: _org_order(conn, r)  # noqa: E731
    else:
        raise PermissionError_("این کلید به سفارشی متصل نیست", code="owner_required")
    if order_number:
        sql += " AND o.order_number = ?"
        params.append(order_number)
    rows = conn.execute(sql + " ORDER BY 1 LIMIT ?", (*params, limit + 1)).fetchall()
    return _page(rows, limit, mapper)


# --------------------------------------------------------------------- shipments
SHIPMENT_TRANSITIONS: dict[str, set[str]] = {
    "booked": {"in_transit", "out_for_delivery", "delivered", "failed"},
    "in_transit": {"out_for_delivery", "delivered", "failed", "returned"},
    "out_for_delivery": {"delivered", "failed", "returned"},
    "failed": {"returned"},
}


def update_shipment_status(conn, *, client: dict, shipment_id: int | None = None, tracking_code: str | None = None,
                           status: str, reason: str | None = None) -> dict:
    """Advance a carrier shipment. Supplier keys reach only their own shipments; platform keys
    (carrier integrations) may address any shipment by id or tracking code."""
    if status not in {s for v in SHIPMENT_TRANSITIONS.values() for s in v}:
        raise ValidationError("وضعیت مرسوله نامعتبر است", details={"allowed": sorted({s for v in SHIPMENT_TRANSITIONS.values() for s in v})})
    if client["owner_type"] == "supplier" and client.get("supplier_id"):
        scope_sql, scope_params = " AND fo.supplier_id = ?", [client["supplier_id"]]
    elif client["owner_type"] == "platform":
        scope_sql, scope_params = "", []
    else:
        raise PermissionError_("این کلید اجازه به‌روزرسانی مرسوله ندارد", code="owner_required")
    if shipment_id is not None:
        where, params = "s.id = ?", [shipment_id]
    elif tracking_code:
        where, params = "s.tracking_code = ?", [tracking_code]
    else:
        raise ValidationError("شناسه یا کد رهگیری مرسوله الزامی است")
    row = conn.execute(f"""SELECT s.id, s.status, s.fulfillment_order_id, fo.supplier_id, fo.order_id FROM shipments s
                           JOIN fulfillment_orders fo ON fo.id=s.fulfillment_order_id WHERE {where}{scope_sql}""",
                       (*params, *scope_params)).fetchone()
    if not row:
        raise NotFoundError("مرسوله یافت نشد")
    if row["status"] == status:
        return {"id": row["id"], "status": status, "changed": False}
    if status not in SHIPMENT_TRANSITIONS.get(row["status"], set()):
        raise ConflictError("تغییر وضعیت مرسوله مجاز نیست", code="invalid_transition",
                            details={"from": row["status"], "to": status})
    stamp = api_keys.now_iso()
    conn.execute("""UPDATE shipments SET status=?, updated_at=?, delivered_at=CASE WHEN ?='delivered' THEN ? ELSE delivered_at END,
                    failure_reason=CASE WHEN ?='failed' THEN ? ELSE failure_reason END WHERE id=?""",
                 (status, stamp, status, stamp, status, (reason or "")[:300] or None, row["id"]))
    audit(conn, actor_user_id=_actor_for(conn, client), action="partner_shipment.status_changed", entity_type="shipment",
          entity_id=row["id"], metadata={"client_id": client["client_id"], "from": row["status"], "to": status})
    return {"id": row["id"], "status": status, "previous_status": row["status"], "changed": True}


# ------------------------------------------------------------------------ credit
def credit_balance(conn, *, client: dict) -> dict:
    from app.services import credit_contract_service as contracts

    org_id = require_organization(client)
    org = conn.execute("SELECT id, credit_limit_minor FROM organizations WHERE id=?", (org_id,)).fetchone()
    if not org:
        raise NotFoundError("سازمان یافت نشد")
    sums = {r["entry_type"]: int(r["total"]) for r in conn.execute(
        "SELECT entry_type, COALESCE(SUM(amount_minor),0) AS total FROM credit_ledger_entries WHERE organization_id=? GROUP BY entry_type",
        (org_id,)).fetchall()}
    allocated = sums.get("allocation", 0) + sums.get("adjustment", 0)
    reserved = sums.get("reservation", 0) - sums.get("release", 0) - sums.get("capture", 0)
    out = {"organization_id": org_id, "currency": "IRR", "credit_limit_minor": int(org["credit_limit_minor"]),
           "allocated_minor": allocated, "reserved_minor": max(reserved, 0), "consumed_minor": sums.get("capture", 0),
           "contract": None}
    contract = contracts.live_contract(conn, org_id)
    if contract:
        out["contract"] = {"id": contract["id"], "status": contract["status"], "limit_minor": int(contract["limit_minor"]),
                           "outstanding_minor": int(contracts.outstanding_minor(conn, contract["id"]))}
        out["contract"]["available_minor"] = max(out["contract"]["limit_minor"] - out["contract"]["outstanding_minor"], 0)
    return out


# -------------------------------------------------------------- inbound registry
INBOUND_HANDLERS: dict[str, dict] = {}


def register_inbound(source: str, *, scope: str, description: str) -> Callable:
    if scope not in api_keys.SCOPES:
        raise ValueError(scope)

    def deco(fn: Callable) -> Callable:
        INBOUND_HANDLERS[source] = {"handler": fn, "scope": scope, "description": description}
        return fn

    return deco


@register_inbound("supplier.price_stock", scope="offers:write",
                  description="فید قیمت و موجودی تأمین‌کننده: items[] با product_id یا supplier_sku")
def _handle_price_stock(conn, client: dict, payload: dict) -> dict:
    supplier_id = require_supplier(client)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 500:
        raise ValidationError("فهرست items باید بین ۱ تا ۵۰۰ ردیف باشد")
    results = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError("ردیف نامعتبر", details={"index": idx})
        if item.get("product_id") is None and isinstance(item.get("supplier_sku"), str):
            row = conn.execute("SELECT product_id FROM seller_offers WHERE supplier_id=? AND supplier_sku=? ORDER BY id LIMIT 1",
                               (supplier_id, item["supplier_sku"].strip())).fetchone()
            if not row:
                results.append({"index": idx, "status": "not_found"})
                continue
            item = {**item, "product_id": int(row["product_id"])}
        data = {k: item[k] for k in ("product_id", "supplier_location_id", "selling_price_minor", "stock_quantity",
                                    "supplier_sku", "lead_time_days") if k in item}
        try:
            offer, created = upsert_offer(conn, client=client, data=data)
        except ApiError as exc:
            results.append({"index": idx, "status": "error", "code": exc.code, "message": exc.message})
            continue
        results.append({"index": idx, "status": "created" if created else "updated", "offer_id": offer["id"]})
    return {"processed": len(results), "items": results}


@register_inbound("shipment.tracking", scope="shipments:write",
                  description="بازگشت وضعیت رهگیری مرسوله: shipment_id یا tracking_code و status")
def _handle_tracking(conn, client: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("بدنه نامعتبر است")
    sid = _int(payload.get("shipment_id"), "shipment_id", optional=True)
    code = payload.get("tracking_code") if isinstance(payload.get("tracking_code"), str) else None
    return update_shipment_status(conn, client=client, shipment_id=sid, tracking_code=code,
                                  status=payload.get("status"), reason=payload.get("reason"))


def process_inbound(db, *, client: dict, source: str, idempotency_key: str | None, raw_body: bytes,
                    signature_header: str | None, master_key: str) -> tuple[int, dict]:
    """Verify HMAC, enforce idempotency, log raw payload, dispatch to the registered handler."""
    spec = INBOUND_HANDLERS.get(source)
    if spec is None:
        raise NotFoundError("منبع ورودی ناشناخته است", code="unknown_source")
    if spec["scope"] not in client["scopes"]:
        raise PermissionError_("این کلید مجوز لازم را ندارد", code="insufficient_scope",
                               details={"required_scopes": [spec["scope"]]})
    if not client.get("signing_salt"):
        raise ConflictError("برای این مشتری کلید امضا صادر نشده است", code="signing_secret_missing")
    secret = api_keys.derive_signing_secret(master_key, client["signing_salt"])
    if not api_keys.verify_signature(secret, signature_header, raw_body):
        raise AuthenticationError("امضای درخواست نامعتبر یا منقضی است", code="invalid_signature")
    key = (idempotency_key or "").strip()
    if not 8 <= len(key) <= 120:
        raise ValidationError("سرآیند Idempotency-Key الزامی است (۸ تا ۱۲۰ نویسه)", code="idempotency_key_required")
    if len(raw_body) > 1_000_000:
        raise ValidationError("حجم بدنه بیش از حد مجاز است", code="payload_too_large")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("بدنه JSON نامعتبر است", code="invalid_json")
    digest = hashlib.sha256(raw_body).hexdigest()
    cid = client["client_id"]
    with db.write_transaction() as conn:
        prior = conn.execute("SELECT * FROM partner_inbound_messages WHERE client_id=? AND source=? AND idempotency_key=?",
                             (cid, source, key)).fetchone()
        if prior is not None:
            if prior["payload_hash"] != digest:
                raise ConflictError("این Idempotency-Key قبلاً با بدنه متفاوت استفاده شده است", code="idempotency_conflict")
            if prior["status"] == "processed":
                return 200, {"inbound_id": prior["id"], "status": "processed", "replayed": True,
                             "result": json.loads(prior["result_json"] or "{}")}
            message_id = int(prior["id"])
        else:
            message_id = conn.execute(
                """INSERT INTO partner_inbound_messages (client_id, source, idempotency_key, payload_hash, payload_raw, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (cid, source, key, digest, raw_body.decode("utf-8"), api_keys.now_iso())).lastrowid
    try:
        with db.write_transaction() as conn:
            result = spec["handler"](conn, client, payload)
            conn.execute("UPDATE partner_inbound_messages SET status='processed', result_json=?, error=NULL, processed_at=? WHERE id=?",
                         (json.dumps(result, ensure_ascii=False, default=str), api_keys.now_iso(), message_id))
            audit(conn, actor_user_id=_actor_for(conn, client), action="partner_inbound.processed",
                  entity_type="partner_inbound_message", entity_id=message_id, metadata={"client_id": cid, "source": source})
    except ApiError as exc:
        with db.write_transaction() as conn:
            conn.execute("UPDATE partner_inbound_messages SET status='failed', error=?, processed_at=? WHERE id=?",
                         (f"{exc.code}: {exc.message}"[:500], api_keys.now_iso(), message_id))
        raise
    return 201, {"inbound_id": message_id, "status": "processed", "replayed": False, "result": result}
