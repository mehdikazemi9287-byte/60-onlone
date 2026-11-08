"""Owned customer inquiries and procurement requests; no quote or sale is fabricated."""

import hashlib, json
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from app.core.deps import current_user, get_db, require_auth, get_settings
from app.core.errors import ValidationError, NotFoundError, ConflictError, PermissionError_
from app.services import catalog_service

bp = Blueprint("customer_requests", __name__, url_prefix="/api/v1")


def _text(value, name, limit, required=True):
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise ValidationError("مقدار " + name + " نامعتبر است")
    return value.strip()


def _positive(value, name, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
        raise ValidationError("مقدار " + name + " نامعتبر است")
    return value


def _view(row):
    out = dict(row)
    out["items"] = json.loads(out.pop("items_json"))
    out.pop("payload_hash", None)
    out.pop("idempotency_key", None)
    return out


def _owned(db, request_id):
    row = db.query_one("SELECT * FROM customer_requests WHERE id=?", (request_id,))
    if row is None or (
        current_user()["role"] != "admin" and row["user_id"] != current_user()["id"]
    ):
        raise NotFoundError("درخواست یافت نشد")
    return row


@bp.post("/requests")
@require_auth()
def create_request():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("درخواست نامعتبر است")
    kind = body.get("kind", "price")
    if kind not in ("price", "procurement", "support"):
        raise ValidationError("نوع درخواست نامعتبر است")
    subject = _text(body.get("subject"), "موضوع", 200)
    message = _text(body.get("message", ""), "توضیحات", 4000, False)
    key = _text(request.headers.get("Idempotency-Key"), "شناسه درخواست", 128)
    db = get_db()
    uid = current_user()["id"]
    org_id = body.get("organization_id")
    if org_id is not None:
        _positive(org_id, "سازمان", 2147483647)
        if not db.query_one(
            "SELECT 1 FROM organization_memberships WHERE organization_id=? AND user_id=? AND status=?",
            (org_id, uid, "active"),
        ):
            raise NotFoundError("عضویت فعال سازمانی یافت نشد")
    rows = body.get("items", [])
    if not isinstance(rows, list) or len(rows) > 50 or (kind != "support" and not rows):
        raise ValidationError("یک تا ۵۰ کالای معتبر انتخاب کنید")
    items = []
    seen = set()
    for entry in rows:
        if not isinstance(entry, dict):
            raise ValidationError("قلم درخواست نامعتبر است")
        slug = _text(entry.get("slug"), "نشانی کالا", 200)
        qty = _positive(entry.get("quantity"), "تعداد")
        if slug in seen:
            raise ValidationError("کالای تکراری؛ تعداد را در همان ردیف اصلاح کنید")
        seen.add(slug)
        p = catalog_service.get_product_by_slug(db, slug, exponent=get_settings().currency_exponent)
        items.append(
            {
                "slug": p["slug"],
                "product_id": p["id"],
                "master_product_id": p.get("master_product_id"),
                "name": p["title_fa"],
                "quantity": qty,
            }
        )
    payload = {
        "kind": kind,
        "subject": subject,
        "message": message,
        "organization_id": org_id,
        "items": items,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    with db.write_transaction() as conn:
        old = conn.execute(
            "SELECT * FROM customer_requests WHERE user_id=? AND idempotency_key=?", (uid, key)
        ).fetchone()
        if old:
            if old["payload_hash"] != digest:
                raise ConflictError(
                    "این شناسه قبلاً برای درخواست دیگری استفاده شده است", code="idempotency_conflict"
                )
            return jsonify({"request": _view(old), "created": False}), 200
        from app.services.product_channel_policy import require_master,require_sku
        for entry in (items if kind!="support" else []):
            if entry["product_id"]>0:require_sku(conn,entry["product_id"],"organization" if org_id else "retail")
            else:require_master(conn,entry["master_product_id"],"organization" if org_id else "retail")
        cursor = conn.execute(
            "INSERT INTO customer_requests(user_id,organization_id,kind,subject,message,items_json,idempotency_key,payload_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                org_id,
                kind,
                subject,
                message,
                json.dumps(items, ensure_ascii=False),
                key,
                digest,
                now,
                now,
            ),
        )
        rid = cursor.lastrowid
        conn.execute(
            "INSERT INTO customer_request_events(request_id,actor_user_id,status,message,created_at) VALUES (?,?,?,?,?)",
            (rid, uid, "open", "درخواست ثبت شد", now),
        )
        row = conn.execute("SELECT * FROM customer_requests WHERE id=?", (rid,)).fetchone()
    return jsonify({"request": _view(row), "created": True}), 201


def _list(admin=False):
    db = get_db()
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        raise ValidationError("صفحه نامعتبر است")
    if page < 1:
        raise ValidationError("صفحه نامعتبر است")
    where = "1=1" if admin else "user_id=?"
    params = [] if admin else [current_user()["id"]]
    total = db.query_one("SELECT COUNT(*) n FROM customer_requests WHERE " + where, params)["n"]
    rows = db.query(
        "SELECT * FROM customer_requests WHERE " + where + " ORDER BY id DESC LIMIT 25 OFFSET ?",
        [*params, (page - 1) * 25],
    )
    return jsonify(
        {
            "items": [_view(x) for x in rows],
            "total": total,
            "page": page,
            "pages": max(1, (total + 24) // 25),
        }
    )


@bp.get("/requests")
@require_auth()
def list_my_requests():
    return _list()


@bp.get("/admin/requests")
@require_auth("admin")
def list_admin_requests():
    return _list(True)


@bp.get("/requests/<int:request_id>")
@require_auth()
def request_detail(request_id):
    db = get_db()
    row = _owned(db, request_id)
    events = db.query(
        "SELECT status,message,created_at FROM customer_request_events WHERE request_id=? ORDER BY id",
        (request_id,),
    )
    from app.services import request_quote_service as rq
    with db.read_transaction() as conn:
        quotes = rq.list_for_request(conn, request_id)
    return jsonify({"request": _view(row), "events": [dict(x) for x in events], "quotes": quotes})


@bp.patch("/admin/requests/<int:request_id>")
@require_auth("admin")
def update_request(request_id):
    db = get_db()
    _owned(db, request_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("درخواست نامعتبر است")
    status = body.get("status")
    message = _text(body.get("response"), "پاسخ", 4000)
    if status not in ("reviewing", "answered", "closed"):
        raise ValidationError("وضعیت نامعتبر است")
    now = datetime.now(timezone.utc).isoformat()
    with db.write_transaction() as conn:
        old = conn.execute("SELECT * FROM customer_requests WHERE id=?", (request_id,)).fetchone()
        if old["status"] != status or old["response"] != message:
            conn.execute(
                "UPDATE customer_requests SET status=?,response=?,updated_at=? WHERE id=?",
                (status, message, now, request_id),
            )
            conn.execute(
                "INSERT INTO customer_request_events(request_id,actor_user_id,status,message,created_at) VALUES (?,?,?,?,?)",
                (request_id, current_user()["id"], status, message, now),
            )
    return request_detail(request_id)


@bp.post("/admin/requests/<int:request_id>/quotes")
@require_auth("admin")
def create_request_quote(request_id):
    from app.services import request_quote_service as rq
    body = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        return jsonify({"quote": rq.create(conn, request_id=request_id, actor=current_user()["id"], data=body)}), 201


@bp.post("/requests/<int:request_id>/quotes/<int:quote_id>/accept")
@require_auth()
def accept_request_quote(request_id, quote_id):
    from app.services import request_quote_service as rq
    body = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        return jsonify(rq.accept(conn, user_id=current_user()["id"], request_id=request_id, quote_id=quote_id, address=body.get("address")))
