"""Marketplace storefront (public), supplier offer management and catalog administration."""
from flask import Blueprint, g, jsonify, request

from app.api.v1.enterprise_procurement import _idempotent
from app.core.deps import authenticate_request, current_user, get_db, require_auth
from app.core.errors import ApiError, PermissionError_, ValidationError
from app.services import catalog_metrics, catalog_structure_service, marketplace_offer_service as offers
from app.services import pack_catalog, pack_service, storefront_service as store
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("marketplace", __name__, url_prefix="/api/v1")


def _int(name, default):
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        raise ValidationError(f"{name} نامعتبر است")


def _opt_int(name):
    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(f"{name} نامعتبر است")
    if value < 0:
        raise ValidationError(f"{name} نامعتبر است")
    return value


def _viewer_orgs() -> tuple:
    """Organization ids of an optionally authenticated viewer (for organization/contract price tiers)."""
    if not request.headers.get("Authorization"):
        return ()
    try:
        authenticate_request()
    except ApiError:
        return ()
    with get_db().read_transaction() as conn:
        return tuple(r[0] for r in conn.execute(
            "SELECT organization_id FROM organization_memberships WHERE user_id=? AND status='active'", (g.current_user["id"],)))


# ── Public storefront ──

@bp.get("/storefront/taxonomy")
def taxonomy():
    with get_db().read_transaction() as conn:
        return jsonify({"items": store.taxonomy(conn)})


@bp.get("/storefront/brands")
def brands():
    with get_db().read_transaction() as conn:
        return jsonify({"items": store.brands(conn)})


@bp.get("/storefront/products")
def products():
    with get_db().read_transaction() as conn:
        return jsonify(store.search(conn, q=request.args.get("q"), category=request.args.get("category") or None,
                                    brand=request.args.get("brand") or None, availability=request.args.get("availability") or None,
                                    sort=request.args.get("sort", "relevance"), page=_int("page", 1), page_size=_int("page_size", 24),
                                    group="sku" if request.args.get("group") == "sku" else "family", size=request.args.get("size") or None,
                                    min_price=_opt_int("min_price"), max_price=_opt_int("max_price")))


@bp.get("/storefront/products/<slug>")
def product(slug: str):
    orgs = _viewer_orgs()
    with get_db().read_transaction() as conn:
        return jsonify(store.product(conn, slug, viewer_org_ids=orgs))


@bp.get("/storefront/packs")
def packs():
    with get_db().read_transaction() as conn:
        return jsonify({"items": pack_service.list_packs(conn, kind=request.args.get("kind") or None,
                                                         audience=request.args.get("audience") or None)})


@bp.get("/storefront/packs/<slug>")
def pack(slug: str):
    with get_db().read_transaction() as conn:
        return jsonify({"pack": pack_service.detail(conn, slug)})


@bp.get("/storefront/pack-compare")
def pack_compare():
    slugs = [s for s in (request.args.get("slugs") or "").split(",") if s]
    with get_db().read_transaction() as conn:
        return jsonify({"items": pack_service.compare(conn, slugs)})


# ── Supplier offers ──

def _supplier(conn) -> int:
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب تأمین‌کننده برای این کاربر یافت نشد")
    return sid


@bp.get("/supplier/marketplace/catalog")
@require_auth()
def supplier_catalog():
    with get_db().read_transaction() as conn:
        _supplier(conn)
        return jsonify({"items": offers.sellable_catalog(conn, q=request.args.get("q"))})


@bp.get("/supplier/marketplace/offers")
@require_auth()
def supplier_offers():
    with get_db().read_transaction() as conn:
        return jsonify({"items": offers.list_mine(conn, supplier_id=_supplier(conn))})


@bp.post("/supplier/marketplace/offers")
@require_auth()
def supplier_offer_create():
    data = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        sid = _supplier(conn)
        return _idempotent(conn, lambda: jsonify({"offer": offers.create(conn, supplier_id=sid, actor=current_user()["id"], data=data)}))


@bp.put("/supplier/marketplace/offers/<int:offer_id>")
@require_auth()
def supplier_offer_update(offer_id: int):
    data = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        sid = _supplier(conn)
        return _idempotent(conn, lambda: jsonify({"offer": offers.update(conn, supplier_id=sid, offer_id=offer_id,
                                                                          actor=current_user()["id"], data=data)}))


@bp.post("/supplier/marketplace/offers/<int:offer_id>/confirm")
@require_auth()
def supplier_offer_confirm(offer_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"offer": offers.confirm(conn, supplier_id=_supplier(conn), offer_id=offer_id, actor=current_user()["id"])})


# ── Catalog administration ──

@bp.get("/admin/catalog/metrics")
@require_auth("admin")
def admin_metrics():
    with get_db().read_transaction() as conn:
        return jsonify(catalog_metrics.metrics(conn))


@bp.post("/admin/catalog/structure/apply")
@require_auth("admin")
def admin_structure():
    with get_db().write_transaction() as conn:
        stats = catalog_structure_service.apply(conn)
        packs_report = pack_catalog.apply(conn)
    return jsonify({"structure": stats, "packs": packs_report})


# ── Budget pack builder (public) ──

@bp.post("/storefront/pack-builder")
def pack_builder():
    from app.services import pack_builder_service
    with get_db().read_transaction() as conn:
        return jsonify(pack_builder_service.suggest(conn, request.get_json(silent=True) or {}))


# ── Stock alerts ("notify me when available") ──

@bp.get("/storefront/products/<slug>/alert")
@require_auth()
def alert_get(slug: str):
    from app.services import commerce_ops_service as ops
    with get_db().read_transaction() as conn:
        return jsonify({"status": ops.alert_status(conn, current_user()["id"], slug)})


@bp.post("/storefront/products/<slug>/alert")
@require_auth()
def alert_on(slug: str):
    from app.services import commerce_ops_service as ops
    with get_db().write_transaction() as conn:
        return jsonify(ops.subscribe(conn, current_user()["id"], slug))


@bp.delete("/storefront/products/<slug>/alert")
@require_auth()
def alert_off(slug: str):
    from app.services import commerce_ops_service as ops
    with get_db().write_transaction() as conn:
        return jsonify(ops.unsubscribe(conn, current_user()["id"], slug))


# ── Supplier contract organizations ──

@bp.get("/supplier/marketplace/organizations")
@require_auth()
def supplier_contract_orgs():
    with get_db().read_transaction() as conn:
        return jsonify({"items": offers.contract_organizations(conn, supplier_id=_supplier(conn))})


# ── Pack administration ──

@bp.get("/admin/packs")
@require_auth("admin")
def admin_packs():
    with get_db().read_transaction() as conn:
        return jsonify({"items": pack_service.admin_list(conn)})


@bp.post("/admin/packs")
@require_auth("admin")
def admin_pack_create():
    data = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify({"pack": pack_service.admin_save(conn, actor=current_user()["id"], data=data)}))


@bp.put("/admin/packs/<int:pack_id>")
@require_auth("admin")
def admin_pack_update(pack_id: int):
    data = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        return _idempotent(conn, lambda: jsonify({"pack": pack_service.admin_save(conn, actor=current_user()["id"], data=data, pack_id=pack_id)}))


@bp.post("/admin/packs/<int:pack_id>/<action>")
@require_auth("admin")
def admin_pack_status(pack_id: int, action: str):
    with get_db().write_transaction() as conn:
        return jsonify({"pack": pack_service.admin_status(conn, actor=current_user()["id"], pack_id=pack_id, action=action)})


# ── Catalog review → publish ──

@bp.get("/admin/catalog/review")
@require_auth("admin")
def admin_catalog_review():
    with get_db().read_transaction() as conn:
        return jsonify({"items": catalog_structure_service.review_queue(conn)})


@bp.post("/admin/catalog/products/<int:master_product_id>/visibility")
@require_auth("admin")
def admin_catalog_visibility(master_product_id: int):
    data = request.get_json(silent=True)
    from app.core.errors import ValidationError
    if not isinstance(data, dict) or type(data.get("visible")) is not bool:
        raise ValidationError("visible باید مقدار بولی صریح باشد")
    with get_db().write_transaction() as conn:
        catalog_structure_service.apply(conn)  # make sure the variant has its family and SKU
        return jsonify({"item": catalog_structure_service.set_visibility(conn, master_product_id=master_product_id,
                                                                         visible=data["visible"], reason=data.get("reason"))})


@bp.post("/cart/packs/<slug>")
@require_auth()
def cart_add_pack(slug: str):
    from app.services import cart_service
    # Idempotent: a retry/double click with the same Idempotency-Key does not add the pack twice.
    count = (request.get_json(silent=True) or {}).get("count", 1)
    return jsonify(cart_service.add_pack(get_db(), user_id=current_user()["id"], slug=slug, count=count,
                                         idempotency_key=request.headers.get("Idempotency-Key"), endpoint=request.path))


# ── Phase 2: Buy Box — all seller offers for a product and the winner ──

@bp.get("/storefront/products/<slug>/offers")
def product_offers_buy_box(slug: str):
    from app.core.errors import NotFoundError
    from app.services import cashier_service
    orgs = _viewer_orgs()
    org_id = _opt_int("organization_id")
    quantity = _int("quantity", 1)
    with get_db().read_transaction() as conn:
        row = conn.execute("SELECT id FROM products WHERE slug=? AND is_active=1", (slug,)).fetchone()
        if row is None:
            raise NotFoundError("کالا یافت نشد")
        ctx = None
        if org_id is not None and org_id in orgs:
            ctx = cashier_service.buyer_context(conn, user_id=g.current_user["id"], organization_id=org_id,
                                                use_credit=False)
        return jsonify(cashier_service.buy_box(conn, int(row["id"]), ctx, quantity=quantity))
