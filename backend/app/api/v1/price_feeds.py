"""فید محصولات: Torob Product API v3 (pull, EdDSA JWT) و خروجی باسلام برای فروشنده.

  POST /api/v1/feeds/torob/v3/products     Torob crawler (X-Torob-Token + X-Torob-Token-Version: 1)
  GET  /api/v1/supplier/feeds/basalam      seller's own offers in Basalam bulk-upload shape (?format=csv)
Off unless EXTERNAL_CHANNELS_ENABLED=1 (closed ecosystem). Env: TOROB_PUBLIC_KEY (Ed25519 PEM from Torob), TOROB_AUD (default: host of PUBLIC_BASE_URL), TOROB_PRICE_UNIT.
"""
from __future__ import annotations

import csv
import io
import os
from urllib.parse import urlsplit

import jwt
from flask import Blueprint, Response, jsonify, request

from app.core.deps import current_user, get_db, get_settings, require_auth
from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.services import price_feed_service as feeds
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("price_feeds", __name__, url_prefix="/api/v1")


def _base_url() -> str:
    base = (get_settings().public_base_url or "").rstrip("/")
    return base or request.host_url.rstrip("/")


def external_channels_enabled() -> bool:
    """Closed ecosystem by default: nothing leaves for outside marketplaces/comparison sites until the owner opts in."""
    return os.environ.get("EXTERNAL_CHANNELS_ENABLED", "").strip() == "1"


def _torob_error(status: int, message: str):
    return jsonify({"error": message}), status


@bp.post("/feeds/torob/v3/products")
def torob_products():
    if not external_channels_enabled():
        return _torob_error(404, "not found")
    key = (os.environ.get("TOROB_PUBLIC_KEY") or "").replace("\\n", "\n").strip()
    if not key:
        return _torob_error(503, "Torob feed is not configured")
    token = request.headers.get("X-Torob-Token", "")
    if request.headers.get("X-Torob-Token-Version") != "1" or not token or len(token) > 4096:
        return _torob_error(401, "invalid token")
    aud = os.environ.get("TOROB_AUD") or urlsplit(_base_url()).hostname or ""
    try:
        jwt.decode(token, key, algorithms=["EdDSA"], audience=aud, options={"require": ["exp", "aud"]}, leeway=30)
    except jwt.PyJWTError:
        return _torob_error(401, "invalid token")
    body = request.get_json(silent=True)
    try:
        with get_db().read_transaction() as conn:
            return jsonify(feeds.torob_products(conn, body, base_url=_base_url()))
    except ValidationError as exc:
        return _torob_error(400, exc.message)


_BASALAM_COLS = ("sku", "name", "brand", "category_id", "category_name", "price_rial", "stock", "preparation_days",
                 "weight_g", "source_url", "photos", "description")


@bp.get("/supplier/feeds/basalam")
@require_auth()
def basalam_feed():
    if not external_channels_enabled():
        raise NotFoundError("این امکان فعال نیست", code="external_channels_disabled")
    with get_db().read_transaction() as conn:
        sid = current_supplier_id(conn, current_user()["id"])
        if not sid:
            raise PermissionError_("حساب تأمین‌کننده برای این کاربر یافت نشد")
        out = feeds.basalam_export(conn, sid, base_url=_base_url())
    if request.args.get("format") != "csv":
        return jsonify(out)
    from app.adapters.accounting.finance_formats import safe_cell
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_BASALAM_COLS)
    for it in out["items"]:
        w.writerow([safe_cell("|".join(it[c]) if c == "photos" else ("" if it[c] is None else it[c])) for c in _BASALAM_COLS])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=basalam-products.csv"})
