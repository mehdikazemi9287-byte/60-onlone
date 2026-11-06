"""In-person: store locator, collect-in-store, visit appointments (مراجعهٔ حضوری)."""
import json
import re

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import NotFoundError, PermissionError_, ValidationError
from app.services import in_person_service as svc
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("in_person", __name__, url_prefix="/api/v1")


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d


def _supplier(conn) -> int:
    sid = current_supplier_id(conn, current_user()["id"])
    if not sid:
        raise PermissionError_("حساب فروشنده یافت نشد")
    return sid


@bp.get("/stores")
def stores():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.store_locator(conn, city=request.args.get("city"),
                                                   province=request.args.get("province"))})


@bp.get("/me/fulfillments/<int:fo_id>/pickup")
@require_auth()
def pickup_options(fo_id: int):
    with get_db().read_transaction() as conn:
        return jsonify(svc.pickup_locations(conn, user_id=current_user()["id"], fulfillment_order_id=fo_id))


@bp.post("/me/fulfillments/<int:fo_id>/pickup")
@require_auth()
def choose_pickup(fo_id: int):
    loc = _body().get("location_id")
    if type(loc) is not int:
        raise ValidationError("فروشگاه دریافت را انتخاب کنید")
    with get_db().write_transaction() as conn:
        return jsonify(svc.choose_pickup(conn, user_id=current_user()["id"], fulfillment_order_id=fo_id,
                                         location_id=loc)), 201


@bp.post("/supplier/fulfillments/<int:fo_id>/pickup/confirm")
@require_auth()
def confirm_pickup(fo_id: int):
    with get_db().write_transaction() as conn:
        return jsonify(svc.confirm_pickup(conn, supplier_id=_supplier(conn), actor_user_id=current_user()["id"],
                                          fulfillment_order_id=fo_id, code=_body().get("code")))


_DAYS = ("sat", "sun", "mon", "tue", "wed", "thu", "fri")
_SPAN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def _check_hours(hours) -> None:
    """{"sat": "09:00-18:00", "fri": "closed", ...}; up to two spans per day ("09:00-13:00,16:00-20:00")."""
    if hours is None:
        return
    if not isinstance(hours, dict) or set(hours) - set(_DAYS):
        raise ValidationError("ساعت کاری باید برای روزهای sat تا fri باشد، مثل {\"sat\": \"09:00-18:00\"}")
    for day, v in hours.items():
        if v == "closed":
            continue
        spans = v.split(",") if isinstance(v, str) else []
        if not 1 <= len(spans) <= 2 or not all(_SPAN.match(x.strip()) and x.strip()[:5] < x.strip()[6:] for x in spans):
            raise ValidationError(f"ساعت «{day}» نامعتبر است (مثل 09:00-18:00 یا closed)", code="invalid_hours")


@bp.get("/supplier/locations/in-person")
@require_auth()
def my_locations():
    with get_db().read_transaction() as conn:
        sid = _supplier(conn)
        rows = conn.execute("SELECT id, province, city, district, address, status, can_pickup, accepts_walk_in, "
                            "accepts_appointments, public_title, public_phone, operating_hours_json FROM supplier_locations "
                            "WHERE supplier_id=? ORDER BY id", (sid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            raw = d.pop("operating_hours_json")
            try:
                d["opening_hours"] = json.loads(raw) if raw else None
            except ValueError:
                d["opening_hours"] = None
            for k in ("can_pickup", "accepts_walk_in", "accepts_appointments"):
                d[k] = bool(d[k])
            out.append(d)
        return jsonify({"items": out})


@bp.put("/supplier/locations/<int:location_id>/in-person")
@require_auth()
def set_in_person(location_id: int):
    d = _body()
    allowed = {"can_pickup", "accepts_walk_in", "accepts_appointments", "public_title", "public_phone", "opening_hours"}
    if set(d) - allowed:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(set(d) - allowed)})
    with get_db().write_transaction() as conn:
        sid = _supplier(conn)
        if not conn.execute("SELECT 1 FROM supplier_locations WHERE id=? AND supplier_id=?", (location_id, sid)).fetchone():
            raise NotFoundError("محل فروشنده یافت نشد")
        sets, args = [], []
        for k in ("can_pickup", "accepts_walk_in", "accepts_appointments"):
            if k in d:
                if type(d[k]) is not bool:
                    raise ValidationError(f"«{k}» باید true یا false باشد")
                sets.append(f"{k}=?"); args.append(int(d[k]))
        for k, lim in (("public_title", 120), ("public_phone", 20)):
            if k in d:
                v = d[k]
                if v is not None and (not isinstance(v, str) or len(v) > lim):
                    raise ValidationError(f"«{k}» نامعتبر است")
                sets.append(f"{k}=?"); args.append(v.strip() if isinstance(v, str) else None)
        if "opening_hours" in d:
            _check_hours(d["opening_hours"])
            sets.append("operating_hours_json=?")
            args.append(json.dumps(d["opening_hours"], ensure_ascii=False) if d["opening_hours"] else None)
        if sets:
            conn.execute(f"UPDATE supplier_locations SET {', '.join(sets)}, updated_at=datetime('now') WHERE id=?",
                         (*args, location_id))
        return jsonify({"items": svc.store_locator(conn, supplier_id=sid)})


@bp.get("/me/visits")
@require_auth()
def my_visits():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.my_visits(conn, user_id=current_user()["id"])})


@bp.post("/me/visits")
@require_auth()
def book_visit():
    with get_db().write_transaction() as conn:
        return jsonify({"visit": svc.book_visit(conn, user_id=current_user()["id"], data=_body())}), 201


@bp.post("/me/visits/<int:visit_id>/cancel")
@require_auth()
def cancel_visit(visit_id: int):
    with get_db().write_transaction() as conn:
        return jsonify({"visit": svc.cancel_visit(conn, user_id=current_user()["id"], visit_id=visit_id)})


@bp.get("/supplier/visits")
@require_auth()
def seller_visits():
    with get_db().read_transaction() as conn:
        return jsonify({"items": svc.seller_visits(conn, supplier_id=_supplier(conn))})


@bp.post("/supplier/visits/<int:visit_id>/<decision>")
@require_auth()
def seller_decide(visit_id: int, decision: str):
    with get_db().write_transaction() as conn:
        return jsonify({"visit": svc.seller_decide_visit(conn, supplier_id=_supplier(conn), visit_id=visit_id,
                                                         decision=decision)})
