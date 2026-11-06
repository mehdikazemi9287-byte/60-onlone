"""همکاری در فروش (affiliate): join, record a referral landing, dashboard, seller bonus, admin rates."""
from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import PermissionError_, ValidationError
from app.services import affiliate_service as aff
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("affiliates", __name__, url_prefix="/api/v1")


def _body() -> dict:
    d = request.get_json(silent=True)
    if d is not None and not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d or {}


@bp.post("/me/affiliate")
@require_auth()
def join():
    with get_db().write_transaction() as conn:
        return jsonify({"affiliate": aff.join(conn, user_id=current_user()["id"], code=_body().get("code"))}), 201


@bp.get("/me/affiliate")
@require_auth()
def dashboard():
    with get_db().write_transaction() as conn:
        return jsonify(aff.dashboard(conn, user_id=current_user()["id"]))


@bp.post("/me/referral")
@require_auth()
def landed():
    with get_db().write_transaction() as conn:
        return jsonify(aff.record_landing(conn, buyer_user_id=current_user()["id"], code=_body().get("code")))


@bp.put("/supplier/affiliate-bonus")
@require_auth()
def seller_bonus():
    with get_db().write_transaction() as conn:
        sid = current_supplier_id(conn, current_user()["id"])
        if not sid:
            raise PermissionError_("حساب فروشنده یافت نشد")
        return jsonify({"affiliate_bonus_bps": aff.set_seller_bonus(conn, supplier_id=sid, bonus_bps=_body().get("bonus_bps"))})


@bp.post("/admin/affiliate-rates")
@require_auth("admin")
def admin_rate():
    d = _body()
    cat, rate = d.get("category_id"), d.get("rate_bps")
    if (cat is not None and type(cat) is not int) or type(rate) is not int or not 0 <= rate <= 2000:
        raise ValidationError("category_id عدد یا null و rate_bps بین ۰ تا ۲۰۰۰")
    with get_db().write_transaction() as conn:
        conn.execute("INSERT INTO affiliate_rates (category_id, rate_bps) VALUES (?,?)", (cat, rate))
        conn.execute("INSERT INTO audit_logs(actor_user_id, action, entity_type, entity_id, metadata_json) VALUES (?,?,?,?,?)",
                     (current_user()["id"], "affiliate_rate_set", "category", str(cat), f'{{"rate_bps": {rate}}}'))
        return jsonify({"ok": True}), 201
