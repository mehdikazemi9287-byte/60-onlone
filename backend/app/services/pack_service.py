"""Packs: merchandising compositions of real catalog variants. A pack is never its own product.

Pricing comes only from verified offers of its items; if any required item lacks one, the pack is
quote-only (no estimated total). A diversity gate refuses packs whose composition duplicates or
nearly duplicates another published pack.
"""
from __future__ import annotations

import json

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services import sale_eligibility as se
from app.services import product_channel_policy as policy
from app.services import text_norm as tn

KIND_FA = {"livelihood": "معیشتی", "occasion": "مناسبتی", "theme": "موضوعی", "organizational": "سازمانی", "custom": "سفارشی"}
TIER_FA = {"economy": "اقتصادی", "standard": "استاندارد", "complete": "کامل", "premium": "ممتاز", "executive": "ویژه مدیران"}
AUDIENCE_FA = {"household": "خانوار", "organization": "سازمان", "employee_gift": "هدیه کارکنان", "office": "محیط اداری"}
SIMILARITY_LIMIT = 0.7


def _items(conn, pack_id: int) -> list[dict]:
    prov = ",".join(f"'{p}'" for p in se.allowed_provenance())
    rows = conn.execute(f"""
        SELECT pi.*, m.canonical_name_fa, m.brand, m.variant_label, m.attributes_json, m.image_urls_json, m.family_id,
               p.id AS sku_id, p.slug, p.category_id
        FROM pack_items pi JOIN master_products m ON m.id = pi.master_product_id
        LEFT JOIN products p ON p.id = (SELECT MIN(p2.id) FROM products p2 WHERE p2.master_product_id = m.id
                                         AND p2.is_active = 1 AND p2.provenance IN ({prov}))
        WHERE pi.pack_id = ? ORDER BY pi.sort_order, pi.id""", (pack_id,)).fetchall()
    out = []
    for r in rows:
        offer = se.eligible_offer_conn(conn, r["sku_id"]) if r["sku_id"] else None
        attrs = json.loads(r["attributes_json"] or "{}")
        unit = se.unit_price(conn, offer, r["quantity"]) if offer is not None and offer["id"] else None
        out.append({"master_product_id": r["master_product_id"], "sku_id": r["sku_id"], "slug": r["slug"],
                    "title_fa": r["canonical_name_fa"], "brand_fa": r["brand"], "variant_label": r["variant_label"],
                    "image_url": (json.loads(r["image_urls_json"] or "[]") or [None])[0], "quantity": r["quantity"],
                    "required": bool(r["required"]), "weight_g": attrs.get("weight_g"), "unit_price_minor": unit,
                    "line_total_minor": unit * r["quantity"] if unit else None, "available": unit is not None,
                    "family_id": r["family_id"], "category_id": r["category_id"],"allowed_channels":list(policy.channels((policy.master_policy(conn,r["master_product_id"]) or {}).get("supply_channel"))) if (policy.master_policy(conn,r["master_product_id"]) or {}).get("status")=="active" else []})
    return out


def _summary(conn, pack, items: list[dict]) -> dict:
    required = [i for i in items if i["required"]]
    priced = bool(required) and all(i["available"] for i in required)
    total = sum(i["line_total_minor"] for i in items if i["line_total_minor"]) if priced else None
    weight = sum((i["weight_g"] or 0) * i["quantity"] for i in items)
    brands = sorted({i["brand_fa"] for i in items if i["brand_fa"]})
    return {
        "id": pack["id"], "slug": pack["slug"], "title_fa": pack["title_fa"], "kind": pack["kind"], "kind_fa": KIND_FA[pack["kind"]],
        "tier": pack["tier"], "tier_fa": TIER_FA.get(pack["tier"]), "occasion": pack["occasion"], "audience": pack["audience"],
        "audience_fa": AUDIENCE_FA[pack["audience"]], "purpose_fa": pack["purpose_fa"], "household_size": pack["household_size"],
        "item_count": len(items), "unit_count": sum(i["quantity"] for i in items), "food_weight_g": weight or None,
        "brands": brands, "customizable": bool(pack["customizable"]), "substitution_policy": pack["substitution_policy"],
        "min_order_qty": pack["min_order_qty"], "lead_time_days": pack["lead_time_days"], "packaging_fa": pack["packaging_fa"],
        "availability": "purchasable" if priced else "quote_only",
        "allowed_channels":sorted(set.intersection(*[set(i["allowed_channels"]) for i in required])) if required else [],
        "price_minor": total, "price_per_person_minor": (total // pack["household_size"]) if total and pack["household_size"] else None,
        "image_url": next((i["image_url"] for i in items if i["image_url"]), None), "provenance": pack["provenance"],
    }


def _published(conn):
    prov = ",".join(f"'{p}'" for p in se.allowed_provenance())
    return conn.execute(f"SELECT * FROM packs WHERE status='published' AND provenance IN ({prov}) ORDER BY sort_order, id").fetchall()


def list_packs(conn, *, kind=None, audience=None) -> list[dict]:
    return [_summary(conn, p, _items(conn, p["id"])) for p in _published(conn)
            if (not kind or p["kind"] == kind) and (not audience or p["audience"] == audience)]


def search(conn, q_tokens: list[str]) -> list[dict]:
    out = []
    for p in _published(conn):
        items = _items(conn, p["id"])
        text = tn.normalize(" ".join([p["title_fa"], p["purpose_fa"], p["occasion"] or ""] + [i["title_fa"] for i in items]))
        words = set(text.split())
        if all(t in words or any(w.startswith(t) for w in words) for t in q_tokens):
            out.append(_summary(conn, p, items))
    return out


def alternatives(conn, item: dict) -> list[dict]:
    """Same product type (leaf category), same family other size, weight within ±30% — never unrelated goods."""
    if not item["category_id"]:
        return []
    prov = ",".join(f"'{p}'" for p in se.allowed_provenance())
    fam = conn.execute("SELECT category_id FROM product_families WHERE id=?", (item["family_id"],)).fetchone() if item["family_id"] else None
    leaf = fam["category_id"] if fam else None
    if not leaf:
        return []
    rows = conn.execute(f"""
        SELECT m.id, m.canonical_name_fa, m.brand, m.variant_label, m.attributes_json, p.slug, p.id AS sku_id
        FROM master_products m JOIN product_families f ON f.id=m.family_id
        JOIN products p ON p.master_product_id=m.id AND p.is_active=1 AND p.provenance IN ({prov})
        WHERE f.category_id=? AND m.id<>? AND m.provenance IN ({prov}) ORDER BY m.id""", (leaf, item["master_product_id"])).fetchall()
    out = []
    for r in rows:
        w = json.loads(r["attributes_json"] or "{}").get("weight_g")
        if item["weight_g"] and w and not (0.7 * item["weight_g"] <= w <= 1.3 * item["weight_g"]):
            continue
        out.append({"master_product_id": r["id"], "title_fa": r["canonical_name_fa"], "brand_fa": r["brand"],
                    "variant_label": r["variant_label"], "slug": r["slug"]})
    return out[:6]


def detail(conn, slug: str) -> dict:
    p = next((x for x in _published(conn) if x["slug"] == slug), None)
    if not p:
        raise NotFoundError("پک یافت نشد")
    items = _items(conn, p["id"])
    for i in items:
        i["alternatives"] = alternatives(conn, i) if p["substitution_policy"] != "none" else []
    return _summary(conn, p, items) | {"items": items, "description_fa": p["description_fa"]}


def compare(conn, slugs: list[str]) -> list[dict]:
    if not 2 <= len(slugs) <= 4:
        raise ValidationError("برای مقایسه ۲ تا ۴ پک انتخاب کنید")
    return [detail(conn, s) for s in slugs]


def similarity(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def quality_gate(conn, pack_id: int) -> None:
    """Refuse a composition that duplicates (or ≥70% overlaps) another published pack."""
    mine = {r[0] for r in conn.execute("SELECT master_product_id FROM pack_items WHERE pack_id=?", (pack_id,))}
    if len(mine) < 3:
        raise ConflictError("پک باید حداقل ۳ قلم واقعی داشته باشد", code="pack_too_small")
    for other in conn.execute("SELECT id, title_fa FROM packs WHERE status='published' AND id<>?", (pack_id,)):
        theirs = {r[0] for r in conn.execute("SELECT master_product_id FROM pack_items WHERE pack_id=?", (other["id"],))}
        if similarity(mine, theirs) >= SIMILARITY_LIMIT:
            raise ConflictError(f"ترکیب این پک تقریباً با «{other['title_fa']}» یکسان است", code="pack_duplicate")


# ── Administration (platform admin) ──

EDITABLE = ("title_fa", "kind", "tier", "occasion", "audience", "purpose_fa", "household_size", "min_order_qty", "lead_time_days",
            "substitution_policy", "customizable", "packaging_fa", "description_fa", "sort_order")


def _event(conn, pack_id, actor, action):
    snap = dict(conn.execute("SELECT * FROM packs WHERE id=?", (pack_id,)).fetchone())
    snap["items"] = [dict(r) for r in conn.execute("SELECT master_product_id, quantity, required FROM pack_items WHERE pack_id=? ORDER BY sort_order", (pack_id,))]
    conn.execute("INSERT INTO pack_events (pack_id, actor_user_id, action, snapshot_json) VALUES (?,?,?,?)",
                 (pack_id, actor, action, json.dumps(snap, ensure_ascii=False, default=str)))


def admin_list(conn) -> list[dict]:
    out = []
    for p in conn.execute("SELECT * FROM packs ORDER BY sort_order, id"):
        items = _items(conn, p["id"])
        out.append(_summary(conn, p, items) | {"status": p["status"], "items": items, "events": [dict(r) for r in conn.execute(
            """SELECT e.action, e.created_at, u.full_name AS actor FROM pack_events e JOIN users u ON u.id=e.actor_user_id
               WHERE e.pack_id=? ORDER BY e.id DESC LIMIT 20""", (p["id"],))]})
    return out


def admin_save(conn, *, actor: int, data: dict, pack_id: int | None = None) -> dict:
    fields = {k: data.get(k) for k in EDITABLE if k in data}
    allowed = {"kind": set(KIND_FA), "tier": set(TIER_FA) | {None}, "audience": set(AUDIENCE_FA),
               "substitution_policy": {"none", "same_type", "same_type_and_size", "ask"}}
    for k, values in allowed.items():
        if k in fields and fields[k] not in values:
            raise ValidationError(f"مقدار {k} نامعتبر است")
    for k in ("household_size", "min_order_qty", "lead_time_days", "sort_order"):
        if fields.get(k) is not None and (isinstance(fields[k], bool) or not isinstance(fields[k], int) or fields[k] < 0):
            raise ValidationError(f"مقدار {k} نامعتبر است")
    if "customizable" in fields:
        fields["customizable"] = 1 if fields["customizable"] else 0
    if pack_id is None:
        slug = data.get("slug")
        if not isinstance(slug, str) or not slug.strip() or not all(ch.isalnum() or ch == "-" for ch in slug):
            raise ValidationError("شناسه نشانی پک باید با حروف لاتین، عدد و خط تیره باشد")
        if not fields.get("title_fa") or not fields.get("kind") or not fields.get("audience") or not fields.get("purpose_fa"):
            raise ValidationError("عنوان، نوع، مخاطب و کاربرد پک الزامی است")
        if conn.execute("SELECT 1 FROM packs WHERE slug=?", (slug,)).fetchone():
            raise ConflictError("این شناسه قبلاً استفاده شده است")
        cols = ["slug", "status", "provenance"] + list(fields)
        pack_id = conn.execute(f"INSERT INTO packs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                               (slug.strip(), "draft", "real", *fields.values())).lastrowid
        action = "created"
    else:
        if not conn.execute("SELECT 1 FROM packs WHERE id=?", (pack_id,)).fetchone():
            raise NotFoundError("پک یافت نشد")
        if fields:
            conn.execute(f"UPDATE packs SET {', '.join(f'{k}=?' for k in fields)}, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                         (*fields.values(), pack_id))
        action = "updated"
    if "items" in data:
        items = data["items"]
        if not isinstance(items, list) or len(items) > 40:
            raise ValidationError("اقلام پک نامعتبر است")
        conn.execute("DELETE FROM pack_items WHERE pack_id=?", (pack_id,))
        for i, it in enumerate(items):
            mid = it.get("master_product_id") if isinstance(it, dict) else None
            qty = it.get("quantity", 1) if isinstance(it, dict) else None
            if isinstance(mid, bool) or not isinstance(mid, int) or isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 1000:
                raise ValidationError("قلم پک نامعتبر است")
            if not conn.execute("""SELECT 1 FROM master_products m JOIN products p ON p.master_product_id=m.id
                                   WHERE m.id=? AND m.provenance='real' AND p.is_active=1""", (mid,)).fetchone():
                raise ValidationError("فقط کالای واقعی و قابل نمایش کاتالوگ در پک مجاز است")
            conn.execute("INSERT INTO pack_items (pack_id, master_product_id, quantity, required, sort_order) VALUES (?,?,?,?,?)",
                         (pack_id, mid, qty, 1 if it.get("required", True) else 0, i))
        if conn.execute("SELECT status FROM packs WHERE id=?", (pack_id,)).fetchone()["status"] == "published":
            quality_gate(conn, pack_id)  # a published pack must keep passing the diversity gate
    _event(conn, pack_id, actor, action)
    return next(p for p in admin_list(conn) if p["id"] == pack_id)


def admin_status(conn, *, actor: int, pack_id: int, action: str) -> dict:
    row = conn.execute("SELECT status FROM packs WHERE id=?", (pack_id,)).fetchone()
    if not row:
        raise NotFoundError("پک یافت نشد")
    target = {"publish": "published", "unpublish": "draft", "archive": "archived"}.get(action)
    if not target:
        raise ValidationError("اقدام نامعتبر است")
    if row["status"] == target:
        raise ConflictError("پک از قبل در این وضعیت است")
    if target == "published":
        quality_gate(conn, pack_id)
    conn.execute("UPDATE packs SET status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (target, pack_id))
    _event(conn, pack_id, actor, {"published": "published", "draft": "unpublished", "archived": "archived"}[target])
    return next(p for p in admin_list(conn) if p["id"] == pack_id)
