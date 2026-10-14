"""Customer-facing commerce operations: stock alerts + notifications, retail returns, employee benefits.

* Stock alerts fire only when a SKU gets a verified, eligible offer (never on DEMO data).
* Returns: requested → approved | rejected → received → refund_pending → refunded; the refund is a record
  of what finance paid back (amount + bank reference). No money moves here. Events are append-only.
* Benefits: HR runs a program (fixed pack, choice of packs, or existing employee credit); employees choose;
  HR turns the closed program into ONE organization purchase request with aggregated real items.
"""
from __future__ import annotations

import json

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import sale_eligibility as se


def notify(conn, user_id: int, kind: str, title: str, body: str | None = None, link: str | None = None) -> None:
    conn.execute("INSERT INTO user_notifications (user_id, kind, title, body, link) VALUES (?,?,?,?,?)",
                 (user_id, kind, title[:200], (body or "")[:1000] or None, link))


def notifications(conn, user_id: int) -> dict:
    items = [dict(r) for r in conn.execute("SELECT * FROM user_notifications WHERE user_id=? ORDER BY id DESC LIMIT 100", (user_id,))]
    return {"items": items, "unread": sum(1 for i in items if not i["read_at"])}


def mark_read(conn, user_id: int, notification_id: int | None = None) -> None:
    conn.execute(f"""UPDATE user_notifications SET read_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                     WHERE user_id=? AND read_at IS NULL {'AND id=?' if notification_id else ''}""",
                 (user_id, notification_id) if notification_id else (user_id,))


# ── Stock alerts ──

def _sku(conn, slug: str):
    row = conn.execute("SELECT id, slug, title_fa, provenance, is_active FROM products WHERE slug=?", (slug,)).fetchone()
    if not row or not row["is_active"] or row["provenance"] not in se.allowed_provenance():
        raise NotFoundError("محصول یافت نشد")
    return row


def subscribe(conn, user_id: int, slug: str) -> dict:
    sku = _sku(conn, slug)
    offer = se.eligible_offer_conn(conn, sku["id"])
    if offer is not None and offer["id"]:
        raise ConflictError("این کالا هم‌اکنون قابل خرید است", code="already_available")
    conn.execute("""INSERT INTO stock_alerts (user_id, product_id, status) VALUES (?,?,'active')
                    ON CONFLICT(user_id, product_id) DO UPDATE SET status='active', notified_at=NULL""", (user_id, sku["id"]))
    return {"slug": slug, "status": "active"}


def unsubscribe(conn, user_id: int, slug: str) -> dict:
    sku = _sku(conn, slug)
    conn.execute("UPDATE stock_alerts SET status='cancelled' WHERE user_id=? AND product_id=? AND status='active'", (user_id, sku["id"]))
    return {"slug": slug, "status": "cancelled"}


def alert_status(conn, user_id: int, slug: str) -> str | None:
    row = conn.execute("""SELECT a.status FROM stock_alerts a JOIN products p ON p.id=a.product_id
                          WHERE a.user_id=? AND p.slug=?""", (user_id, slug)).fetchone()
    return row["status"] if row else None


def fire_alerts(conn, product_id: int) -> int:
    """Called after offer changes: notify subscribers once the SKU is really purchasable."""
    offer = se.eligible_offer_conn(conn, product_id)
    if offer is None or not offer["id"]:
        return 0
    sku = conn.execute("SELECT slug, title_fa FROM products WHERE id=?", (product_id,)).fetchone()
    rows = conn.execute("SELECT id, user_id FROM stock_alerts WHERE product_id=? AND status='active'", (product_id,)).fetchall()
    for r in rows:
        notify(conn, r["user_id"], "stock_available", f"«{sku['title_fa']}» موجود شد", "قیمت و موجودی توسط فروشنده تأیید شده است.",
               f"/products/{sku['slug']}")
        conn.execute("UPDATE stock_alerts SET status='notified', notified_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (r["id"],))
    return len(rows)


# ── Retail returns ──

RETURN_FLOW = {"approve": ("requested", "approved"), "reject": ("requested", "rejected"), "receive": ("approved", "received"),
               "refund_pending": ("received", "refund_pending"), "refund": ("refund_pending", "refunded")}
RETURN_FA = {"requested": "درخواست ثبت شد", "approved": "تأیید شد", "rejected": "رد شد", "received": "کالا دریافت شد",
             "refund_pending": "در انتظار بازپرداخت", "refunded": "بازپرداخت ثبت شد", "cancelled": "لغو شد"}


def _return_view(conn, row) -> dict:
    d = dict(row)
    d["items"] = json.loads(d.pop("items_json"))
    d["status_fa"] = RETURN_FA[d["status"]]
    d["events"] = [dict(r) for r in conn.execute("""SELECT e.status, e.note, e.created_at, u.full_name AS actor FROM order_return_events e
                                                    JOIN users u ON u.id=e.actor_user_id WHERE e.return_id=? ORDER BY e.id""", (d["id"],))]
    o = conn.execute("SELECT order_number, total_minor FROM orders WHERE id=?", (d["order_id"],)).fetchone()
    d["order_number"], d["order_total_minor"] = o["order_number"], o["total_minor"]
    return d


def _order(conn, user_id: int, order_number: str):
    o = conn.execute("SELECT * FROM orders WHERE order_number=? AND user_id=?", (order_number, user_id)).fetchone()
    if not o:
        raise NotFoundError("سفارش یافت نشد")
    return o


def request_return(conn, *, user_id: int, order_number: str, data: dict) -> dict:
    o = _order(conn, user_id, order_number)
    if o["status"] not in ("paid", "fulfilling", "delivered"):
        raise ConflictError("برای این سفارش امکان ثبت مرجوعی وجود ندارد")
    if conn.execute("""SELECT 1 FROM order_return_requests WHERE order_id=? AND status IN ('requested','approved','received','refund_pending')""",
                    (o["id"],)).fetchone():
        raise ConflictError("برای این سفارش یک درخواست مرجوعی باز وجود دارد", code="return_open")
    reason = data.get("reason")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
        raise ValidationError("علت مرجوعی را بنویسید")
    ordered = {r["product_id"]: r for r in conn.execute("SELECT product_id, title_fa, quantity FROM order_items WHERE order_id=?", (o["id"],))}
    already: dict = {}
    for r in conn.execute("SELECT items_json FROM order_return_requests WHERE order_id=? AND status NOT IN ('rejected','cancelled')", (o["id"],)):
        for it in json.loads(r["items_json"]):
            already[it["product_id"]] = already.get(it["product_id"], 0) + it["quantity"]
    items = []
    for it in data.get("items") or []:
        pid, qty = (it or {}).get("product_id"), (it or {}).get("quantity")
        if pid not in ordered or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ValidationError("قلم مرجوعی نامعتبر است")
        if qty > ordered[pid]["quantity"] - already.get(pid, 0):
            raise ValidationError("تعداد مرجوعی از تعداد خریداری‌شده بیشتر است")
        items.append({"product_id": pid, "title_fa": ordered[pid]["title_fa"], "quantity": qty})
    if not items:
        raise ValidationError("حداقل یک قلم برای مرجوعی انتخاب کنید")
    rid = conn.execute("INSERT INTO order_return_requests (order_id, user_id, items_json, reason) VALUES (?,?,?,?)",
                       (o["id"], user_id, json.dumps(items, ensure_ascii=False), reason.strip())).lastrowid
    conn.execute("INSERT INTO order_return_events (return_id, actor_user_id, status, note) VALUES (?,?,?,?)", (rid, user_id, "requested", reason.strip()))
    return _return_view(conn, conn.execute("SELECT * FROM order_return_requests WHERE id=?", (rid,)).fetchone())


def returns_for_order(conn, *, user_id: int, order_number: str) -> list[dict]:
    o = _order(conn, user_id, order_number)
    return [_return_view(conn, r) for r in conn.execute("SELECT * FROM order_return_requests WHERE order_id=? ORDER BY id DESC", (o["id"],))]


def cancel_return(conn, *, user_id: int, return_id: int) -> dict:
    r = conn.execute("SELECT * FROM order_return_requests WHERE id=? AND user_id=?", (return_id, user_id)).fetchone()
    if not r:
        raise NotFoundError("درخواست مرجوعی یافت نشد")
    if r["status"] != "requested":
        raise ConflictError("فقط درخواست بررسی‌نشده قابل لغو است")
    conn.execute("UPDATE order_return_requests SET status='cancelled', version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (return_id,))
    conn.execute("INSERT INTO order_return_events (return_id, actor_user_id, status, note) VALUES (?,?,?,?)", (return_id, user_id, "cancelled", None))
    return _return_view(conn, conn.execute("SELECT * FROM order_return_requests WHERE id=?", (return_id,)).fetchone())


def admin_returns(conn, status: str | None) -> list[dict]:
    sql = "SELECT * FROM order_return_requests" + (" WHERE status=?" if status else "") + " ORDER BY id DESC LIMIT 200"
    return [_return_view(conn, r) for r in conn.execute(sql, (status,) if status else ())]


def admin_transition(conn, *, actor: int, return_id: int, action: str, data: dict) -> dict:
    r = conn.execute("SELECT * FROM order_return_requests WHERE id=?", (return_id,)).fetchone()
    if not r:
        raise NotFoundError("درخواست مرجوعی یافت نشد")
    if action not in RETURN_FLOW:
        raise ValidationError("اقدام نامعتبر است")
    frm, to = RETURN_FLOW[action]
    if r["status"] != frm:
        raise ConflictError("این تغییر وضعیت مجاز نیست", code="invalid_transition")
    note = (data.get("note") or "").strip()[:1000] or None
    if action == "reject" and not note:
        raise ValidationError("علت رد الزامی است")
    amount = ref = None
    if action == "refund":
        amount, ref = data.get("amount_minor"), (data.get("reference") or "").strip()
        order = conn.execute("SELECT id, total_minor FROM orders WHERE id=?", (r["order_id"],)).fetchone()
        prior = conn.execute("SELECT COALESCE(SUM(refund_amount_minor),0) FROM order_return_requests WHERE order_id=? AND status='refunded'",
                             (r["order_id"],)).fetchone()[0]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or amount > order["total_minor"] - prior:
            raise ValidationError("مبلغ بازپرداخت نامعتبر است یا از مانده سفارش بیشتر است")
        if not 3 <= len(ref) <= 200:
            raise ValidationError("مرجع بانکی بازپرداخت الزامی است")
    changed = conn.execute("""UPDATE order_return_requests SET status=?, refund_amount_minor=COALESCE(?, refund_amount_minor),
                              refund_reference=COALESCE(?, refund_reference), version=version+1, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                              WHERE id=? AND version=?""", (to, amount, ref, return_id, r["version"]))
    if changed.rowcount != 1:
        raise ConflictError("درخواست همزمان تغییر کرد؛ دوباره تلاش کنید", code="stale_version")
    conn.execute("INSERT INTO order_return_events (return_id, actor_user_id, status, note) VALUES (?,?,?,?)",
                 (return_id, actor, to, note or (f"مرجع: {ref}" if ref else None)))
    if to == "refunded":
        total = conn.execute("SELECT total_minor FROM orders WHERE id=?", (r["order_id"],)).fetchone()[0]
        refunded = conn.execute("SELECT COALESCE(SUM(refund_amount_minor),0) FROM order_return_requests WHERE order_id=? AND status='refunded'",
                                (r["order_id"],)).fetchone()[0]
        if refunded >= total:
            conn.execute("UPDATE orders SET status='refunded' WHERE id=?", (r["order_id"],))
    view = _return_view(conn, conn.execute("SELECT * FROM order_return_requests WHERE id=?", (return_id,)).fetchone())
    notify(conn, r["user_id"], "return_status", f"مرجوعی سفارش {view['order_number']}: {RETURN_FA[to]}", note, f"/orders/{view['order_number']}")
    return view


# ── Employee benefits ──

def _member(conn, org: int, user: int):
    m = conn.execute("""SELECT m.* FROM organization_memberships m JOIN organizations o ON o.id=m.organization_id AND o.status='active'
                        WHERE m.organization_id=? AND m.user_id=? AND m.status='active'""", (org, user)).fetchone()
    if not m:
        raise PermissionError_("عضویت فعال در این سازمان لازم است")
    return m


def _hr(conn, org: int, user: int):
    m = _member(conn, org, user)
    if m["role"] != "organization_admin":
        raise PermissionError_("مدیریت برنامه مزایا برای مدیر سازمان است")
    return m


def _packs(conn, ids) -> list[dict]:
    from app.services import pack_service
    out = []
    for pid in ids:
        p = conn.execute("SELECT * FROM packs WHERE id=? AND status='published'", (pid,)).fetchone()
        if p:
            out.append(pack_service._summary(conn, p, pack_service._items(conn, p["id"])))
    return out


def _program_view(conn, row, user_id: int | None = None) -> dict:
    d = dict(row)
    d["pack_ids"] = json.loads(d.pop("pack_ids_json"))
    d["packs"] = _packs(conn, d["pack_ids"])
    counts = {r[0]: r[1] for r in conn.execute("SELECT pack_id, COUNT(*) FROM benefit_selections WHERE program_id=? AND status='selected' GROUP BY 1", (d["id"],))}
    d["selections"] = {"total": sum(counts.values()), "by_pack": [{"pack_id": k, "count": v} for k, v in counts.items()]}
    if user_id:
        mine = conn.execute("SELECT pack_id, status FROM benefit_selections WHERE program_id=? AND user_id=?", (d["id"], user_id)).fetchone()
        d["my_selection"] = dict(mine) if mine else None
    return d


def create_program(conn, *, org: int, actor: int, data: dict) -> dict:
    _hr(conn, org, actor)
    mode = data.get("mode")
    if mode not in ("fixed_pack", "pack_choice", "credit"):
        raise ValidationError("نوع برنامه نامعتبر است")
    title = data.get("title")
    if not isinstance(title, str) or not 3 <= len(title.strip()) <= 200:
        raise ValidationError("عنوان برنامه الزامی است")
    slugs = data.get("pack_slugs") or []
    ids = [r["id"] for s in slugs if (r := conn.execute("SELECT id FROM packs WHERE slug=? AND status='published'", (s,)).fetchone())]
    if len(ids) != len(slugs):
        raise ValidationError("فقط پک‌های منتشرشده قابل انتخاب است")
    if mode == "fixed_pack" and len(ids) != 1:
        raise ValidationError("برنامه پک ثابت دقیقاً یک پک لازم دارد")
    if mode == "pack_choice" and not 2 <= len(ids) <= 6:
        raise ValidationError("برنامه انتخاب پک ۲ تا ۶ پک لازم دارد")
    if mode == "credit" and ids:
        raise ValidationError("برنامه اعتباری پک ندارد؛ از تخصیص اعتبار سازمان استفاده می‌شود")
    pid = conn.execute("""INSERT INTO benefit_programs (organization_id, title, mode, pack_ids_json, note, closes_at, created_by_user_id)
                          VALUES (?,?,?,?,?,?,?)""", (org, title.strip(), mode, json.dumps(ids), (data.get("note") or "")[:1000] or None,
                                                       data.get("closes_at"), actor)).lastrowid
    return _program_view(conn, conn.execute("SELECT * FROM benefit_programs WHERE id=?", (pid,)).fetchone())


def set_program_status(conn, *, org: int, actor: int, program_id: int, status: str) -> dict:
    _hr(conn, org, actor)
    p = conn.execute("SELECT * FROM benefit_programs WHERE id=? AND organization_id=?", (program_id, org)).fetchone()
    if not p:
        raise NotFoundError("برنامه یافت نشد")
    allowed = {"draft": {"open"}, "open": {"closed"}, "closed": set()}
    if status not in allowed[p["status"]]:
        raise ConflictError("این تغییر وضعیت مجاز نیست")
    conn.execute("UPDATE benefit_programs SET status=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (status, program_id))
    if status == "open":
        for m in conn.execute("SELECT user_id FROM organization_memberships WHERE organization_id=? AND status='active'", (org,)):
            notify(conn, m["user_id"], "benefit_open", f"برنامه مزایا: {p['title']}", "انتخاب خود را ثبت کنید.", "/benefits")
    return _program_view(conn, conn.execute("SELECT * FROM benefit_programs WHERE id=?", (program_id,)).fetchone())


def org_programs(conn, *, org: int, actor: int) -> list[dict]:
    m = _member(conn, org, actor)
    rows = conn.execute("SELECT * FROM benefit_programs WHERE organization_id=? ORDER BY id DESC", (org,)).fetchall()
    hr = m["role"] == "organization_admin"
    return [_program_view(conn, r, actor) for r in rows if hr or r["status"] != "draft"]


def my_programs(conn, *, user_id: int) -> list[dict]:
    rows = conn.execute("""SELECT p.* FROM benefit_programs p JOIN organization_memberships m ON m.organization_id=p.organization_id
                           WHERE m.user_id=? AND m.status='active' AND p.status IN ('open','closed') ORDER BY p.id DESC""", (user_id,)).fetchall()
    out = []
    for r in rows:
        v = _program_view(conn, r, user_id)
        if v["mode"] == "credit":
            v["credit"] = [dict(a) for a in conn.execute(
                """SELECT a.id, a.allocated_minor, a.expires_at, a.category_slugs_json, a.per_transaction_limit_minor
                   FROM credit_allocations a JOIN organization_memberships m ON m.id=a.membership_id
                   WHERE a.organization_id=? AND m.user_id=? AND a.status='active'""", (r["organization_id"], user_id))]
        out.append(v)
    return out


def select(conn, *, user_id: int, program_id: int, pack_slug: str | None) -> dict:
    p = conn.execute("SELECT * FROM benefit_programs WHERE id=?", (program_id,)).fetchone()
    if not p:
        raise NotFoundError("برنامه یافت نشد")
    _member(conn, p["organization_id"], user_id)
    if p["status"] != "open":
        raise ConflictError("مهلت انتخاب این برنامه باز نیست")
    if p["mode"] == "credit":
        raise ConflictError("برنامه اعتباری انتخاب پک ندارد")
    ids = json.loads(p["pack_ids_json"])
    pack = conn.execute("SELECT id FROM packs WHERE slug=?", (pack_slug,)).fetchone() if pack_slug else None
    pack_id = ids[0] if p["mode"] == "fixed_pack" else (pack["id"] if pack else None)
    if pack_id not in ids:
        raise ValidationError("پک انتخابی در این برنامه نیست")
    conn.execute("""INSERT INTO benefit_selections (program_id, user_id, pack_id, status) VALUES (?,?,?,'selected')
                    ON CONFLICT(program_id, user_id) DO UPDATE SET pack_id=excluded.pack_id, status='selected',
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""", (program_id, user_id, pack_id))
    return _program_view(conn, p, user_id)


def to_purchase_request(conn, *, org: int, actor: int, program_id: int, destination: dict) -> dict:
    """Aggregate every selection's pack items into ONE organization purchase request (draft)."""
    from app.services import procurement_service as pr_svc
    _hr(conn, org, actor)
    p = conn.execute("SELECT * FROM benefit_programs WHERE id=? AND organization_id=?", (program_id, org)).fetchone()
    if not p:
        raise NotFoundError("برنامه یافت نشد")
    if p["status"] != "closed":
        raise ConflictError("ابتدا مهلت انتخاب را ببندید")
    if p["purchase_request_id"]:
        raise ConflictError("درخواست خرید این برنامه قبلاً ساخته شده است", code="already_created")
    qty: dict = {}
    names: dict = {}
    for s in conn.execute("SELECT pack_id FROM benefit_selections WHERE program_id=? AND status='selected'", (program_id,)):
        for it in conn.execute("""SELECT pi.master_product_id, pi.quantity, m.canonical_name_fa FROM pack_items pi
                                  JOIN master_products m ON m.id=pi.master_product_id WHERE pi.pack_id=?""", (s["pack_id"],)):
            qty[it["master_product_id"]] = qty.get(it["master_product_id"], 0) + it["quantity"]
            names[it["master_product_id"]] = it["canonical_name_fa"]
    if not qty:
        raise ConflictError("هنوز انتخابی ثبت نشده است")
    if not isinstance(destination, dict):
        raise ValidationError("مقصد تحویل الزامی است")
    items = [{"master_product_id": mid, "free_text_description": names[mid], "quantity": q, "unit": "عدد"} for mid, q in qty.items()]
    dest = dict(destination) | {"allocations": [{"item_index": i, "quantity": it["quantity"]} for i, it in enumerate(items)]}
    pr = pr_svc.create_purchase_request(conn, organization_id=org, requester_user_id=actor, title=f"مزایای کارکنان: {p['title']}",
                                        description=f"تجمیع {sum(1 for _ in qty)} قلم از انتخاب کارکنان", items=items, destinations=[dest])
    pr_id = pr["id"] if isinstance(pr, dict) else pr
    conn.execute("UPDATE benefit_programs SET purchase_request_id=? WHERE id=?", (pr_id, program_id))
    return {"purchase_request_id": pr_id, "items": len(items), "units": sum(qty.values())}
