"""Organization payment-policy lifecycle: draft → in_review → approved | rejected | withdrawn.

Approval writes the immutable customer_payment_policies row that procurement finance
enforces. Approved policies are derived as scheduled / active / superseded from their
effective date, so there is no second copy of "which policy applies".

Nothing here invents business values: a draft holds only what its proposer entered,
and only a platform admin who did not propose it can approve it. Demo/test
organizations can only hold TEST policies; real organizations only PRODUCTION ones.
"""
from __future__ import annotations

import datetime
import json

from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError

METHODS = ("cash", "cheque", "credit", "bill")
LIFECYCLE_FA = {"draft": "پیش‌نویس", "in_review": "در بررسی", "approved": "مصوب", "rejected": "ردشده",
                "withdrawn": "انصراف", "scheduled": "مصوب؛ در انتظار تاریخ اجرا", "active": "فعال",
                "superseded": "جایگزین‌شده"}


def _today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _int(v, field, lo=0, hi=10**15, optional=True):
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValidationError(f"{field} نامعتبر است")
    return v


def validate_rules(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("قواعد سیاست باید شیء باشد")
    methods = raw.get("methods")
    if not isinstance(methods, list) or not methods or any(m not in METHODS for m in methods) or len(set(methods)) != len(methods):
        raise ValidationError("حداقل یک روش پرداخت معتبر (نقدی، چکی، اعتباری، برات) لازم است")
    credit = _int(raw.get("credit_limit_minor"), "سقف اعتبار", 1)
    if "credit" in methods and credit is None:
        raise ValidationError("برای روش اعتباری، سقف اعتبار الزامی است")
    if "credit" not in methods:
        credit = None
    rules = {
        "methods": [m for m in METHODS if m in methods],
        "credit_limit_minor": credit,
        "max_parts": _int(raw.get("max_parts"), "حداکثر تعداد اقساط/بخش‌ها", 1, 12, optional=False),
        "max_term_days": _int(raw.get("max_term_days"), "حداکثر مدت سررسید (روز)", 0, 720,
                              optional=not any(m in methods for m in ("cheque", "bill", "credit"))),
        "dual_approval_threshold_minor": _int(raw.get("dual_approval_threshold_minor"), "آستانه تأیید دومرحله‌ای", 1),
        # Fixed controls, shown for transparency; not configurable.
        "separation_of_duties": True,
    }
    return rules


def _date(v) -> str:
    try:
        return datetime.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise ValidationError("تاریخ اجرا باید به شکل YYYY-MM-DD باشد")


def _org(conn, org: int):
    row = conn.execute("SELECT id, display_name, provenance, status FROM organizations WHERE id=?", (org,)).fetchone()
    if not row:
        raise NotFoundError("سازمان یافت نشد")
    return row


def can_propose(conn, org: int, user: dict) -> bool:
    if user["role"] == "admin":
        return True
    return bool(conn.execute("""SELECT 1 FROM organization_memberships WHERE organization_id=? AND user_id=? AND status='active'
                                AND role IN ('organization_admin','organization_finance')""", (org, user["id"])).fetchone())


def _event(conn, draft, action, actor, note=None):
    snap = {k: draft[k] for k in draft.keys() if k not in ("created_at", "updated_at")}
    conn.execute("""INSERT INTO payment_policy_events (draft_id, organization_id, action, actor_user_id, note, snapshot_json)
                    VALUES (?,?,?,?,?,?)""", (draft["id"], draft["organization_id"], action, actor, note,
                                              json.dumps(snap, ensure_ascii=False, sort_keys=True)))


def _draft(conn, org, draft_id):
    row = conn.execute("SELECT * FROM payment_policy_drafts WHERE id=? AND organization_id=?", (draft_id, org)).fetchone()
    if not row:
        raise NotFoundError("پیش‌نویس سیاست یافت نشد")
    return row


def effective_policy_id(conn, org: int) -> int | None:
    row = conn.execute(
        """SELECT p.id FROM customer_payment_policies p LEFT JOIN payment_policy_drafts d ON d.policy_id=p.id
           WHERE p.organization_id=? AND (d.id IS NULL OR d.effective_from <= ?)
           ORDER BY COALESCE(d.effective_from, '') DESC, p.id DESC LIMIT 1""", (org, _today())).fetchone()
    return row["id"] if row else None


def _fields(data: dict, org_row) -> dict:
    env = data.get("environment")
    expected = "production" if org_row["provenance"] == "real" else "test"
    if env != expected:
        raise ConflictError("سازمان واقعی فقط سیاست production و سازمان نمایشی/آزمایشی فقط سیاست test می‌پذیرد",
                            code="environment_mismatch")
    version = data.get("version")
    if not isinstance(version, str) or not 1 <= len(version.strip()) <= 40:
        raise ValidationError("نسخه سیاست الزامی است")
    contract = data.get("contract_reference")
    contract = contract.strip() if isinstance(contract, str) and contract.strip() else None
    if env == "production" and not contract:
        raise ValidationError("برای سیاست واقعی، مرجع قرارداد/مصوبه الزامی است")
    return {"version": version.strip(), "environment": env, "contract_reference": contract,
            "rules_json": json.dumps(validate_rules(data.get("rules")), ensure_ascii=False, sort_keys=True),
            "effective_from": _date(data.get("effective_from"))}


def create(conn, *, org: int, actor: dict, data: dict) -> dict:
    org_row = _org(conn, org)
    if not can_propose(conn, org, actor):
        raise PermissionError_("پیشنهاد سیاست پرداخت برای مدیر پلتفرم یا مدیر/مالی همان سازمان است")
    f = _fields(data, org_row)
    if conn.execute("SELECT 1 FROM payment_policy_drafts WHERE organization_id=? AND version=?", (org, f["version"])).fetchone():
        raise ConflictError("این شماره نسخه قبلاً استفاده شده است")
    draft_id = conn.execute(
        """INSERT INTO payment_policy_drafts (organization_id, version, environment, contract_reference, rules_json,
               effective_from, proposed_by) VALUES (?,?,?,?,?,?,?)""",
        (org, f["version"], f["environment"], f["contract_reference"], f["rules_json"], f["effective_from"], actor["id"])).lastrowid
    _event(conn, _draft(conn, org, draft_id), "created", actor["id"])
    return get(conn, org=org, draft_id=draft_id)


def edit(conn, *, org: int, draft_id: int, actor: dict, data: dict) -> dict:
    d = _draft(conn, org, draft_id)
    if d["status"] != "draft":
        raise ConflictError("فقط پیش‌نویس قابل ویرایش است")
    if d["proposed_by"] != actor["id"] and actor["role"] != "admin":
        raise PermissionError_("فقط پیشنهاددهنده یا مدیر پلتفرم می‌تواند ویرایش کند")
    if data.get("expected_row_version") != d["row_version"]:
        raise ConflictError("پیش‌نویس تغییر کرده است؛ صفحه را تازه کنید", code="stale_version")
    f = _fields(data, _org(conn, org))
    if f["version"] != d["version"] and conn.execute(
            "SELECT 1 FROM payment_policy_drafts WHERE organization_id=? AND version=?", (org, f["version"])).fetchone():
        raise ConflictError("این شماره نسخه قبلاً استفاده شده است")
    conn.execute("""UPDATE payment_policy_drafts SET version=?, environment=?, contract_reference=?, rules_json=?, effective_from=?,
                    row_version=row_version+1, updated_at=? WHERE id=? AND row_version=?""",
                 (f["version"], f["environment"], f["contract_reference"], f["rules_json"], f["effective_from"], _now(),
                  draft_id, d["row_version"]))
    _event(conn, _draft(conn, org, draft_id), "edited", actor["id"])
    return get(conn, org=org, draft_id=draft_id)


def _transition(conn, org, draft_id, actor, frm, to, action, note=None, **extra):
    d = _draft(conn, org, draft_id)
    if d["status"] not in frm:
        raise ConflictError("این تغییر وضعیت برای سیاست مجاز نیست", code="invalid_transition")
    sets = ", ".join(["status=?", "row_version=row_version+1", "updated_at=?"] + [f"{k}=?" for k in extra])
    changed = conn.execute(f"UPDATE payment_policy_drafts SET {sets} WHERE id=? AND row_version=?",
                           (to, _now(), *extra.values(), draft_id, d["row_version"]))
    if changed.rowcount != 1:
        raise ConflictError("سیاست همزمان تغییر کرد؛ دوباره تلاش کنید", code="stale_version")
    _event(conn, _draft(conn, org, draft_id), action, actor["id"], note)
    return get(conn, org=org, draft_id=draft_id)


def submit(conn, *, org: int, draft_id: int, actor: dict) -> dict:
    d = _draft(conn, org, draft_id)
    if d["proposed_by"] != actor["id"] and actor["role"] != "admin":
        raise PermissionError_("فقط پیشنهاددهنده یا مدیر پلتفرم می‌تواند برای بررسی ارسال کند")
    if d["effective_from"] < _today():
        raise ValidationError("تاریخ اجرا نمی‌تواند گذشته باشد")
    return _transition(conn, org, draft_id, actor, ("draft",), "in_review", "submitted", submitted_at=_now())


def withdraw(conn, *, org: int, draft_id: int, actor: dict, note=None) -> dict:
    d = _draft(conn, org, draft_id)
    if d["proposed_by"] != actor["id"] and actor["role"] != "admin":
        raise PermissionError_("فقط پیشنهاددهنده یا مدیر پلتفرم می‌تواند انصراف دهد")
    return _transition(conn, org, draft_id, actor, ("draft", "in_review"), "withdrawn", "withdrawn", note)


def review(conn, *, org: int, draft_id: int, actor: dict, action: str, note) -> dict:
    if actor["role"] != "admin":
        raise PermissionError_("تصویب سیاست پرداخت فقط برای مدیر پلتفرم است")
    d = _draft(conn, org, draft_id)
    if d["proposed_by"] == actor["id"]:
        raise PermissionError_("پیشنهاددهنده نمی‌تواند سیاست خود را تصویب کند (تفکیک وظایف)")
    if action not in ("approve", "reject"):
        raise ValidationError("اقدام باید تصویب یا رد باشد")
    note = note.strip() if isinstance(note, str) and note.strip() else None
    if action == "reject":
        if not note:
            raise ValidationError("علت رد الزامی است")
        return _transition(conn, org, draft_id, actor, ("in_review",), "rejected", "rejected", note,
                           reviewed_by=actor["id"], reviewed_at=_now(), review_note=note)
    if d["status"] != "in_review":
        raise ConflictError("فقط سیاست در حال بررسی قابل تصویب است", code="invalid_transition")
    rules = json.loads(d["rules_json"]) | {"effective_from": d["effective_from"]}
    policy_id = conn.execute(
        """INSERT INTO customer_payment_policies (organization_id, version, contract_reference, rules_json, approved_by,
               proposed_by, environment) VALUES (?,?,?,?,?,?,?)""",
        (org, d["version"], d["contract_reference"] or "—", json.dumps(rules, ensure_ascii=False, sort_keys=True),
         actor["id"], d["proposed_by"], d["environment"])).lastrowid
    return _transition(conn, org, draft_id, actor, ("in_review",), "approved", "approved", note,
                       reviewed_by=actor["id"], reviewed_at=_now(), review_note=note, policy_id=policy_id)


def _shape(conn, row, active_id) -> dict:
    d = dict(row)
    d["rules"] = json.loads(d.pop("rules_json"))
    life = d["status"]
    if life == "approved":
        life = "active" if d["policy_id"] == active_id else ("scheduled" if d["effective_from"] > _today() else "superseded")
    d["lifecycle"], d["lifecycle_fa"] = life, LIFECYCLE_FA[life]
    names = {r["id"]: r["full_name"] for r in conn.execute(
        "SELECT id, full_name FROM users WHERE id IN (?,?)", (d["proposed_by"], d["reviewed_by"] or 0))}
    d["proposer"], d["reviewer"] = names.get(d["proposed_by"]), names.get(d["reviewed_by"])
    return d


def get(conn, *, org: int, draft_id: int) -> dict:
    d = _shape(conn, _draft(conn, org, draft_id), effective_policy_id(conn, org))
    d["events"] = [dict(r) | {"snapshot": None} for r in conn.execute(
        """SELECT e.id, e.action, e.note, e.created_at, u.full_name AS actor FROM payment_policy_events e
           JOIN users u ON u.id=e.actor_user_id WHERE e.draft_id=? ORDER BY e.id""", (draft_id,))]
    return d


def list_for_org(conn, *, org: int, actor: dict) -> dict:
    org_row = _org(conn, org)
    if actor["role"] != "admin" and not can_propose(conn, org, actor):
        raise PermissionError_("مشاهده سیاست پرداخت برای مدیر یا مالی سازمان است")
    active = effective_policy_id(conn, org)
    items = [_shape(conn, r, active) for r in conn.execute(
        "SELECT * FROM payment_policy_drafts WHERE organization_id=? ORDER BY id DESC", (org,))]
    for it in items:
        it["events"] = [dict(r) for r in conn.execute(
            """SELECT e.action, e.note, e.created_at, u.full_name AS actor FROM payment_policy_events e
               JOIN users u ON u.id=e.actor_user_id WHERE e.draft_id=? ORDER BY e.id""", (it["id"],))]
    return {"organization": dict(org_row), "active_policy_id": active,
            "allowed_environment": "production" if org_row["provenance"] == "real" else "test",
            "can_propose": can_propose(conn, org, actor), "can_review": actor["role"] == "admin",
            "items": items}


def review_queue(conn) -> list[dict]:
    active = {}
    out = []
    for r in conn.execute("""SELECT d.*, o.display_name AS organization, o.provenance FROM payment_policy_drafts d
                             JOIN organizations o ON o.id=d.organization_id
                             WHERE d.status IN ('draft','in_review') ORDER BY d.status='in_review' DESC, d.id"""):
        org = r["organization_id"]
        active.setdefault(org, effective_policy_id(conn, org))
        out.append(_shape(conn, r, active[org]) | {"organization": r["organization"], "org_provenance": r["provenance"]})
    return out
