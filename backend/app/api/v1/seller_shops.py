"""Phase 1 — seller shops: public shop pages, self-registration, seller panel, admin review."""
from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import PermissionError_, ValidationError
from app.services import seller_shop_service as shops
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("seller_shops", __name__)


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d


def _my_supplier(conn) -> int:
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب غرفه برای این کاربر یافت نشد")
    return sid


def _page() -> int:
    raw = request.args.get("page", "1")
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 1000:
        raise ValidationError("شماره صفحه نامعتبر است")
    return int(raw)


# ── public ────────────────────────────────────────────────────────────────────
@bp.get("/api/v1/shops")
def list_shops():
    with get_db().read_transaction() as conn:
        return jsonify({"items": shops.list_shops(conn, kind=request.args.get("kind"), q=request.args.get("q"))})


@bp.get("/api/v1/shops/<slug>")
def shop_page(slug: str):
    with get_db().read_transaction() as conn:
        return jsonify(shops.public_shop(conn, slug, page=_page()))


@bp.get("/api/v1/shops/terms")
def terms():
    return jsonify({"version": shops.TERMS_VERSION, "hold_days": shops.hold_days(),
                    "health_targets_bps": shops.HEALTH_TARGETS})


# ── seller ────────────────────────────────────────────────────────────────────
@bp.post("/api/v1/sellers/apply")
@require_auth()
def apply():
    with get_db().write_transaction() as conn:
        return jsonify({"shop": shops.apply(conn, user_id=current_user()["id"], data=_body())}), 201


@bp.get("/api/v1/supplier/shop")
@require_auth()
def my_shop():
    with get_db().read_transaction() as conn:
        sid = _my_supplier(conn)
        return jsonify({"shop": shops.shop_view(conn, sid, private=True), "balance": shops.balance(conn, supplier_id=sid)})


@bp.put("/api/v1/supplier/shop")
@require_auth()
def update_my_shop():
    with get_db().write_transaction() as conn:
        return jsonify({"shop": shops.update_profile(conn, supplier_id=_my_supplier(conn), data=_body())})


@bp.get("/api/v1/supplier/shop/health")
@require_auth()
def my_health():
    with get_db().write_transaction() as conn:
        return jsonify({"health": shops.compute_health(conn, supplier_id=_my_supplier(conn), enforce=False)})


# ── admin ─────────────────────────────────────────────────────────────────────
@bp.get("/api/v1/admin/shop-applications")
@require_auth("admin")
def admin_applications():
    stage = request.args.get("stage", "submitted")
    if stage not in ("submitted", "under_review", "approved", "rejected"):
        raise ValidationError("مرحله نامعتبر است")
    with get_db().read_transaction() as conn:
        return jsonify({"items": shops.applications(conn, stage=stage)})


@bp.post("/api/v1/admin/shop-applications/<int:supplier_id>/review")
@require_auth("admin")
def admin_review(supplier_id: int):
    d = _body()
    with get_db().write_transaction() as conn:
        return jsonify({"shop": shops.review(conn, admin_id=current_user()["id"], supplier_id=supplier_id,
                                             decision=d.get("decision"), note=d.get("note"))})


@bp.post("/api/v1/admin/shops/<int:supplier_id>/health")
@require_auth("admin")
def admin_health(supplier_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"health": shops.compute_health(conn, supplier_id=supplier_id, enforce=True)})


@bp.get("/api/v1/admin/commission-rules")
@require_auth("admin")
def admin_rules():
    with get_db().read_transaction() as conn:
        rows = conn.execute("SELECT * FROM commission_rules ORDER BY seller_kind, category_id, channel").fetchall()
        return jsonify({"items": [dict(r) for r in rows]})


@bp.post("/api/v1/admin/commission-rules")
@require_auth("admin")
def admin_rule_create():
    d = _body()
    kind, cat, channel, rate = d.get("seller_kind"), d.get("category_id"), d.get("channel", "any"), d.get("rate_bps")
    if kind is not None and kind not in ("supplier", "shop", "brand", "partner"):
        raise ValidationError("نوع فروشنده نامعتبر است")
    if cat is not None and type(cat) is not int:
        raise ValidationError("شناسه دسته نامعتبر است")
    if channel not in ("any", "retail", "organization"):
        raise ValidationError("کانال نامعتبر است")
    if type(rate) is not int or not 0 <= rate <= 5000:
        raise ValidationError("کارمزد باید بین ۰ تا ۵۰۰۰ واحد پایه (۰ تا ۵۰٪) باشد")
    with get_db().write_transaction() as conn:
        cur = conn.execute("INSERT INTO commission_rules (seller_kind, category_id, channel, rate_bps, note) VALUES (?,?,?,?,?)",
                           (kind, cat, channel, rate, (d.get("note") or "")[:500] or None))
        conn.execute("INSERT INTO audit_logs(actor_user_id, action, entity_type, entity_id, metadata_json) VALUES (?,?,?,?,?)",
                     (current_user()["id"], "commission_rule_created", "commission_rule", str(cur.lastrowid),
                      f'{{"rate_bps": {rate}}}'))
        return jsonify({"rule": dict(conn.execute("SELECT * FROM commission_rules WHERE id=?", (cur.lastrowid,)).fetchone())}), 201


@bp.put("/api/v1/admin/shops/<int:supplier_id>/commission")
@require_auth("admin")
def admin_shop_commission(supplier_id: int):
    rate = _body().get("rate_bps")
    if rate is not None and (type(rate) is not int or not 0 <= rate <= 5000):
        raise ValidationError("کارمزد باید بین ۰ تا ۵۰۰۰ باشد یا null")
    with get_db().write_transaction() as conn:
        conn.execute("UPDATE suppliers SET commission_rate_bps=? WHERE id=?", (rate, supplier_id))
        return jsonify({"shop": shops.shop_view(conn, supplier_id, private=True)})
