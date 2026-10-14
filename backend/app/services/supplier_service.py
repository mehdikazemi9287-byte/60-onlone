"""Supplier CRUD service. Used by both admin and supplier-portal APIs."""
from __future__ import annotations

import sqlite3
from typing import Any

from app.core.errors import ConflictError, NotFoundError, ValidationError


# ---------------------------------------------------------------------------
# Supplier CRUD
# ---------------------------------------------------------------------------

def create_supplier(
    conn: sqlite3.Connection,
    *,
    legal_name: str,
    display_name: str,
    national_id: str,
    supplier_type: str = "retailer",
    status: str = "pending",
    phone: str | None = None,
    email: str | None = None,
    bank_name: str | None = None,
    bank_account: str | None = None,
    sheba: str | None = None,
    rating_x10: int = 0,
    user_id: int | None = None,
    notes: str | None = None,
) -> dict:
    if not legal_name.strip():
        raise ValidationError("نام حقوقی الزامی است")
    if not national_id.strip():
        raise ValidationError("شناسه ملی الزامی است")

    existing = conn.execute(
        "SELECT id FROM suppliers WHERE national_id = ?", (national_id,)
    ).fetchone()
    if existing:
        raise ConflictError("تأمین‌کننده‌ای با این شناسه ملی قبلاً ثبت شده است",
                            code="supplier_national_id_duplicate")

    valid_types   = {"retailer", "wholesaler", "producer", "distributor", "local_shop"}
    valid_statuses = {"pending", "active", "suspended", "inactive"}
    if supplier_type not in valid_types:
        raise ValidationError(f"نوع تأمین‌کننده باید یکی از {sorted(valid_types)} باشد")
    if status not in valid_statuses:
        raise ValidationError(f"وضعیت باید یکی از {sorted(valid_statuses)} باشد")
    if not (0 <= rating_x10 <= 50):
        raise ValidationError("امتیاز باید بین ۰ تا ۵۰ باشد")

    cursor = conn.execute(
        """
        INSERT INTO suppliers
            (legal_name, display_name, national_id, supplier_type, status,
             phone, email, bank_name, bank_account, sheba, rating_x10, user_id, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (legal_name, display_name, national_id, supplier_type, status,
         phone, email, bank_name, bank_account, sheba, rating_x10, user_id, notes),
    )
    return get_supplier(conn, supplier_id=int(cursor.lastrowid))


def get_supplier(conn: sqlite3.Connection, *, supplier_id: int) -> dict:
    row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if row is None:
        raise NotFoundError("تأمین‌کننده یافت نشد", code="supplier_not_found")
    return dict(row) | {"is_demo": row["provenance"] != "real"}


def update_supplier_status(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    status: str,
) -> dict:
    valid = {"pending", "active", "suspended", "inactive"}
    if status not in valid:
        raise ValidationError(f"وضعیت نامعتبر است، باید یکی از {sorted(valid)} باشد")
    conn.execute(
        "UPDATE suppliers SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, supplier_id),
    )
    return get_supplier(conn, supplier_id=supplier_id)


def list_suppliers(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    supplier_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    sql  = "SELECT * FROM suppliers WHERE 1=1"
    params: list[Any] = []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if supplier_type:
        sql += " AND supplier_type = ?"
        params.append(supplier_type)
    sql += " ORDER BY provenance = 'real' DESC, display_name ASC LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [dict(r) | {"is_demo": r["provenance"] != "real"} for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Location CRUD
# ---------------------------------------------------------------------------

def create_location(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    province: str,
    city: str,
    district: str | None = None,
    address: str | None = None,
    latitude: str | None = None,
    longitude: str | None = None,
    status: str = "active",
    can_pickup: bool = False,
    can_local_delivery: bool = True,
    can_intercity_shipping: bool = False,
    service_radius_km: int | None = None,
    operating_hours_json: str | None = None,
    prep_time_minutes: int = 60,
) -> dict:
    if not province.strip() or not city.strip():
        raise ValidationError("استان و شهر الزامی است")
    cursor = conn.execute(
        """
        INSERT INTO supplier_locations
            (supplier_id, province, city, district, address,
             latitude, longitude, status,
             can_pickup, can_local_delivery, can_intercity_shipping,
             service_radius_km, operating_hours_json, prep_time_minutes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (supplier_id, province.strip(), city.strip(), district, address,
         latitude, longitude, status,
         int(can_pickup), int(can_local_delivery), int(can_intercity_shipping),
         service_radius_km, operating_hours_json, prep_time_minutes),
    )
    return get_location(conn, location_id=int(cursor.lastrowid))


def get_location(conn: sqlite3.Connection, *, location_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM supplier_locations WHERE id = ?", (location_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("شعبه تأمین‌کننده یافت نشد")
    return dict(row)


def list_locations(conn: sqlite3.Connection, *, supplier_id: int) -> list[dict]:
    return [
        dict(r) for r in conn.execute(
            "SELECT * FROM supplier_locations WHERE supplier_id = ? ORDER BY city ASC",
            (supplier_id,),
        ).fetchall()
    ]


def update_location_status(
    conn: sqlite3.Connection,
    *,
    location_id: int,
    status: str,
) -> dict:
    valid = {"active", "inactive"}
    if status not in valid:
        raise ValidationError("وضعیت نامعتبر است")
    conn.execute(
        "UPDATE supplier_locations SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, location_id),
    )
    return get_location(conn, location_id=location_id)


# ---------------------------------------------------------------------------
# Offer CRUD
# ---------------------------------------------------------------------------

def create_offer(
    conn: sqlite3.Connection,
    *,
    product_id: int,
    supplier_id: int,
    supplier_location_id: int,
    selling_price_minor: int,
    stock_quantity: int,
    supplier_sku: str | None = None,
    cost_price_minor: int | None = None,
    status: str = "active",
    min_order_quantity: int = 1,
    fulfillment_type: str = "delivery",
    prep_time_minutes: int | None = None,
    shipping_days: int | None = None,
) -> dict:
    selling_price_minor = exact_nonnegative_integer(selling_price_minor, "قیمت")
    if selling_price_minor < 0:
        raise ValidationError("قیمت نمی‌تواند منفی باشد")
    stock_quantity = exact_nonnegative_integer(stock_quantity, "موجودی")
    if stock_quantity < 0:
        raise ValidationError("موجودی نمی‌تواند منفی باشد")

    # Verify supplier owns location
    loc = conn.execute(
        "SELECT supplier_id FROM supplier_locations WHERE id = ?",
        (supplier_location_id,),
    ).fetchone()
    if loc is None or int(loc["supplier_id"]) != supplier_id:
        raise ValidationError("شعبه به این تأمین‌کننده تعلق ندارد")

    try:
        cursor = conn.execute(
            """
            INSERT INTO seller_offers
                (product_id, supplier_id, supplier_location_id,
                 supplier_sku, selling_price_minor, cost_price_minor,
                 stock_quantity, status, min_order_quantity,
                 fulfillment_type, prep_time_minutes, shipping_days)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (product_id, supplier_id, supplier_location_id,
             supplier_sku, selling_price_minor, cost_price_minor,
             stock_quantity, status, min_order_quantity,
             fulfillment_type, prep_time_minutes, shipping_days),
        )
    except Exception as e:
        if "UNIQUE" in str(e):
            raise ConflictError("این تأمین‌کننده قبلاً برای این محصول در این شعبه آفر دارد",
                                code="offer_duplicate")
        raise
    return get_offer(conn, offer_id=int(cursor.lastrowid))


def get_offer(conn: sqlite3.Connection, *, offer_id: int) -> dict:
    row = conn.execute("SELECT * FROM seller_offers WHERE id = ?", (offer_id,)).fetchone()
    if row is None:
        raise NotFoundError("آفر یافت نشد")
    d=dict(row)
    from app.services.product_channel_policy import offer_fields
    d.update(offer_fields(conn,d["product_id"],d["channel"]))
    return d


def list_offers(
    conn: sqlite3.Connection,
    *,
    supplier_id: int | None = None,
    product_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    sql = """
        SELECT so.*, p.title_fa AS product_name, s.display_name AS supplier_name,
               sl.city, sl.province
        FROM seller_offers so
        JOIN products           p  ON p.id  = so.product_id
        JOIN suppliers          s  ON s.id  = so.supplier_id
        JOIN supplier_locations sl ON sl.id = so.supplier_location_id
        WHERE 1=1
    """
    params: list[Any] = []
    if supplier_id is not None:
        sql += " AND so.supplier_id = ?"
        params.append(supplier_id)
    if product_id is not None:
        sql += " AND so.product_id = ?"
        params.append(product_id)
    if status:
        sql += " AND so.status = ?"
        params.append(status)
    sql += " ORDER BY so.updated_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    from app.services.product_channel_policy import offer_fields
    return [{**dict(r),**offer_fields(conn,r["product_id"],r["channel"])} for r in conn.execute(sql, params).fetchall()]


def update_offer_stock(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    supplier_id: int,
    stock_quantity: int,
) -> dict:
    """Supplier updates their own offer's stock."""
    row = conn.execute(
        "SELECT * FROM seller_offers WHERE id = ? AND supplier_id = ?",
        (offer_id, supplier_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("آفر یافت نشد")
    stock_quantity = exact_nonnegative_integer(stock_quantity, "موجودی")
    if stock_quantity < 0:
        raise ValidationError("موجودی نمی‌تواند منفی باشد")
    if stock_quantity < int(row["stock_reserved"]):
        raise ValidationError("موجودی جدید کمتر از موجودی رزرو شده است")
    conn.execute(
        "UPDATE seller_offers SET stock_quantity = ?, updated_at = datetime('now') WHERE id = ?",
        (stock_quantity, offer_id),
    )
    return get_offer(conn, offer_id=offer_id)


def update_offer_price(
    conn: sqlite3.Connection,
    *,
    offer_id: int,
    supplier_id: int,
    selling_price_minor: int,
) -> dict:
    """Supplier updates their own offer's price. Every change is appended to
    offer_price_history — prepared for future price-trend/audit UI, not
    surfaced anywhere yet."""
    row = conn.execute(
        "SELECT * FROM seller_offers WHERE id = ? AND supplier_id = ?",
        (offer_id, supplier_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("آفر یافت نشد")
    selling_price_minor = exact_nonnegative_integer(selling_price_minor, "قیمت")
    if selling_price_minor < 0:
        raise ValidationError("قیمت نمی‌تواند منفی باشد")
    old_price = int(row["selling_price_minor"])
    conn.execute(
        "UPDATE seller_offers SET selling_price_minor = ?, updated_at = datetime('now') WHERE id = ?",
        (selling_price_minor, offer_id),
    )
    if selling_price_minor != old_price:
        conn.execute(
            """INSERT INTO offer_price_history
                   (offer_id, old_price_minor, new_price_minor, changed_by_supplier_id)
               VALUES (?,?,?,?)""",
            (offer_id, old_price, selling_price_minor, supplier_id),
        )
    return get_offer(conn, offer_id=offer_id)


# ---------------------------------------------------------------------------
# Onboarding lifecycle
#
# Layered on top of (not replacing) the pre-existing `status` operational
# column, which every fulfillment/checkout code path already relies on for
# active/suspended/inactive checks. `onboarding_stage` only governs whether a
# supplier is allowed to go operationally active in the first place.
#
#   draft -> submitted -> under_review -> approved | rejected
#
# On 'approved', `status` is set to 'active' (bridges into the existing
# operational field). On 'rejected', `status` is left at its current value
# (an admin decides separately whether to also suspend/deactivate) — this
# migration never changes `status` on rejection, avoiding any surprise
# interaction with pre-existing code that reads `status` alone.
# ---------------------------------------------------------------------------

_ONBOARDING_TRANSITIONS: dict[str, set[str]] = {
    "draft":         {"submitted"},
    "submitted":     {"under_review", "draft"},
    "under_review":  {"approved", "rejected", "submitted"},
    "approved":      set(),   # terminal for onboarding purposes
    "rejected":      {"draft"},  # supplier may revise and resubmit
}


def advance_onboarding_stage(
    conn: sqlite3.Connection,
    *,
    supplier_id: int,
    to_stage: str,
    actor_user_id: int | None = None,
    note: str | None = None,
) -> dict:
    sup = get_supplier(conn, supplier_id=supplier_id)
    from_stage = sup["onboarding_stage"]

    valid_stages = {"draft", "submitted", "under_review", "approved", "rejected"}
    if to_stage not in valid_stages:
        raise ValidationError(f"مرحله نامعتبر است، باید یکی از {sorted(valid_stages)} باشد")

    allowed = _ONBOARDING_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise ValidationError(
            f"انتقال از «{from_stage}» به «{to_stage}» مجاز نیست"
        )

    conn.execute(
        "UPDATE suppliers SET onboarding_stage = ?, updated_at = datetime('now') WHERE id = ?",
        (to_stage, supplier_id),
    )
    conn.execute(
        """INSERT INTO supplier_onboarding_events
               (supplier_id, from_stage, to_stage, actor_user_id, note)
           VALUES (?,?,?,?,?)""",
        (supplier_id, from_stage, to_stage, actor_user_id, note),
    )

    if to_stage == "approved":
        conn.execute(
            "UPDATE suppliers SET status = 'active', updated_at = datetime('now') WHERE id = ?",
            (supplier_id,),
        )

    return get_supplier(conn, supplier_id=supplier_id)


def list_onboarding_events(conn: sqlite3.Connection, *, supplier_id: int) -> list[dict]:
    return [
        dict(r) for r in conn.execute(
            "SELECT * FROM supplier_onboarding_events WHERE supplier_id = ? ORDER BY created_at ASC",
            (supplier_id,),
        ).fetchall()
    ]


def exact_nonnegative_integer(value, name):
    """Preserve exact minor units/quantities across HTTP and importer callers."""
    import re
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        try:
            result = int(value.strip())
        except ValueError:
            raise ValidationError(f"{name} باید عدد صحیح معتبر باشد")
    else:
        raise ValidationError(f"{name} باید عدد صحیح معتبر باشد")
    if not 0 <= result <= 9223372036854775807:
        raise ValidationError(f"{name} خارج از محدوده مجاز است")
    return result
