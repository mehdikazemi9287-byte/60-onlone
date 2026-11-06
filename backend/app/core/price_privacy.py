"""اکوسیستم بسته: جلوگیری از کشف قیمت.

STOREFRONT_PRICE_VISIBILITY:
  public        — everyone sees prices (default)
  members       — prices only for signed-in users
  organizations — prices only for members of an active organization, sellers and admins (B2B launch)
For hidden viewers every public catalog GET response (PUBLIC_CATALOG) has its price fields (any key containing "price" or ending
"_minor") set to null and carries price_hidden=true; price filters/sorts are refused (they would leak prices by
bisection). Known price-aggregator crawlers are refused on all public endpoints regardless of the setting.
"""
from __future__ import annotations

import os
import re

from flask import g, jsonify, request

MODES = ("public", "members", "organizations")
AGGREGATOR_UA = re.compile(r"torob|emalls|basalam|digikala|snappshop|snapp\s*market|pricebot|price-?compar", re.I)
_PRICE_ARGS = ("min_price", "max_price")
# Public catalog surfaces only — a buyer's own cart, orders and invoices are never redacted.
PUBLIC_CATALOG = ("/api/v1/storefront", "/api/v1/products", "/api/v1/catalog", "/api/v1/categories", "/api/v1/brands",
                  "/api/v1/shops", "/api/v1/stores", "/api/v1/offers", "/api/v1/content", "/api/v1/preorders",
                  "/api/v1/vambi")


def mode() -> str:
    m = (os.environ.get("STOREFRONT_PRICE_VISIBILITY") or "public").strip().lower()
    return m if m in MODES else "organizations"  # unknown value fails closed


def _viewer_allowed() -> bool:
    from app.core.deps import authenticate_request, get_db
    from app.core.errors import ApiError
    if not request.headers.get("Authorization"):
        return False
    try:
        authenticate_request()
    except ApiError:
        return False
    u = g.current_user
    if mode() == "members" or u["role"] == "admin":
        return True
    with get_db().read_transaction() as conn:
        uid = u["id"]
        if conn.execute("SELECT 1 FROM organization_memberships WHERE user_id=? AND status='active' LIMIT 1", (uid,)).fetchone():
            return True
        from app.services.access_admin_service import current_supplier_id
        try:
            return bool(current_supplier_id(conn, uid))
        except ApiError:
            return False


def _redact(v):
    if isinstance(v, dict):
        out, hit = {}, False
        for k, x in v.items():
            if ("price" in k or k.endswith("_minor")) and not isinstance(x, (dict, list)):
                out[k] = None
                hit = hit or "price" in k
            else:
                out[k] = _redact(x)
        if hit:
            out["price_hidden"] = True  # per item, so cards can say "sign in to see the price"
        return out
    if isinstance(v, list):
        return [_redact(x) for x in v]
    return v


def install(app) -> None:
    @app.before_request
    def _price_guard():
        p = request.path
        if not p.startswith("/api/v1/") or p.startswith(("/api/v1/health", "/api/v1/payments/")):
            return None
        if AGGREGATOR_UA.search(request.headers.get("User-Agent", "")):
            return jsonify({"error": {"code": "crawler_blocked", "message": "دسترسی خودکار مجاز نیست"}}), 403
        g.price_hidden = False
        if not p.startswith(PUBLIC_CATALOG) or request.method != "GET":
            return None
        if mode() == "public" or _viewer_allowed():
            return None
        g.price_hidden = True
        if any(a in request.args for a in _PRICE_ARGS) or "price" in (request.args.get("sort") or ""):
            return jsonify({"error": {"code": "login_required_for_prices",
                                      "message": "برای دیدن و مرتب‌سازی قیمت‌ها وارد حساب سازمانی شوید"}}), 403
        return None

    @app.after_request
    def _price_redact(response):
        if getattr(g, "price_hidden", False) and response.is_json and response.status_code < 400:
            data = response.get_json(silent=True)
            if isinstance(data, (dict, list)):
                data = _redact(data)
                if isinstance(data, dict):
                    data["price_hidden"] = True
                response.set_data(jsonify(data).get_data())
        return response
