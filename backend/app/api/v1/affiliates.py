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
        return jsonify({"affiliate": aff.join(conn, user_id=current_user()["id"], code=_body().get("code"),
                                                    accept_terms=_body().get("accept_terms") is True)}), 201


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


# ── payouts ──

def _payout_body() -> dict:
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


@bp.put("/me/affiliate/sheba")
@require_auth()
def my_sheba():
    from app.services import affiliate_payout_service as aps
    d = _payout_body()
    with get_db().write_transaction() as conn:
        return jsonify(aps.set_sheba(conn, user_id=current_user()["id"], sheba=d.get("sheba"), holder=d.get("holder"),
                                     national_id=d.get("national_id")))


@bp.get("/me/affiliate/payouts")
@require_auth()
def my_payouts():
    from app.services import affiliate_payout_service as aps
    with get_db().write_transaction() as conn:
        return jsonify(aps.my_payouts(conn, user_id=current_user()["id"]))


@bp.get("/admin/affiliate-payouts/preview")
@require_auth("admin")
def payout_preview():
    from app.services import affiliate_payout_service as aps
    with get_db().write_transaction() as conn:
        return jsonify({**aps.preview(conn), "unverified": aps.unverified(conn), "batches": aps.list_batches(conn)})


@bp.post("/admin/affiliates/<int:affiliate_id>/verify-sheba")
@require_auth("admin")
def verify_sheba(affiliate_id: int):
    from app.services import affiliate_payout_service as aps
    with get_db().write_transaction() as conn:
        return jsonify(aps.verify_sheba(conn, affiliate_id=affiliate_id, actor_user_id=current_user()["id"],
                                        expected_sheba=(request.get_json(silent=True) or {}).get("sheba")))


@bp.post("/admin/affiliate-payouts/batches")
@require_auth("admin")
def payout_batch_create():
    from app.services import affiliate_payout_service as aps
    with get_db().write_transaction() as conn:
        return jsonify(aps.create_batch(conn, actor_user_id=current_user()["id"])), 201


@bp.get("/admin/affiliate-payouts/batches/<int:batch_id>")
@require_auth("admin")
def payout_batch(batch_id: int):
    from app.services import affiliate_payout_service as aps
    with get_db().read_transaction() as conn:
        return jsonify(aps.batch(conn, batch_id))


@bp.get("/admin/affiliate-payouts/batches/<int:batch_id>/export.csv")
@require_auth("admin")
def payout_batch_export(batch_id: int):
    from flask import Response
    from app.services import affiliate_payout_service as aps
    with get_db().write_transaction() as conn:
        body = aps.export_csv(conn, batch_id=batch_id, actor_user_id=current_user()["id"])
    return Response(body, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=affiliate-payouts-{batch_id}.csv",
                             "Cache-Control": "no-store"})


@bp.post("/admin/affiliate-payouts/<int:payout_id>/<action>")
@require_auth("admin")
def payout_settle(payout_id: int, action: str):
    from app.core.errors import NotFoundError
    from app.services import affiliate_payout_service as aps
    d = _payout_body()
    with get_db().write_transaction() as conn:
        if action == "paid":
            return jsonify(aps.mark_paid(conn, payout_id=payout_id, bank_reference=d.get("bank_reference"),
                                         actor_user_id=current_user()["id"]))
        if action == "failed":
            return jsonify(aps.mark_failed(conn, payout_id=payout_id, reason=d.get("reason"), actor_user_id=current_user()["id"]))
    raise NotFoundError("عملیات نامعتبر است")
