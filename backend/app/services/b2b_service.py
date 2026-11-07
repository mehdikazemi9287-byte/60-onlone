"""شروع سازمانی (B2B-first): حساب سازمان‌ها و فروشگاه‌های طرف قرارداد.

- onboard(): one admin step that opens a business account — the organization (or retail shop) itself, its recorded
  contract, its credit contract (limit + weekly statement + due days) and phone invitations for its people.
  All in ONE transaction and idempotent on the Idempotency-Key, so a retry never opens two accounts.
- Invitations are by Iranian mobile number. They are claimed automatically the first time that number is
  verified (OTP login or linking a phone from inside an account), so the owner just logs in with a code.
- submit_application(): the public "open a business account" form. Closed ecosystem: nothing is created until an
  admin reviews it. Answers the same whatever exists already (no enumeration); limited per phone and per IP.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sqlite3

from app.core.errors import ApiError, ConflictError, NotFoundError, ValidationError
from app.services import audit_service
from app.services import credit_contract_service as ccs
from app.services.otp_service import normalize_phone

BUYER_KINDS = ("organization", "retailer")
ROLES = ("employee", "organization_admin", "procurement_agent", "organization_finance")
STAFF_BANDS = ("1-10", "11-50", "51-200", "201-1000", "1000+")
MONTHLY_BANDS = ("<100m", "100m-500m", "500m-2b", "2b+")
MAX_INVITES = 50
APPS_PER_PHONE_DAY = 3
APPS_PER_IP_DAY = 10
_NATIONAL_ID = re.compile(r"^\d{10,14}$")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class TooManyApplications(ApiError):
    status_code = 429
    code = "b2b_application_rate_limited"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(data: dict, key: str, *, required: bool, lo: int = 2, hi: int = 200) -> str | None:
    v = data.get(key)
    v = v.strip() if isinstance(v, str) else None
    if not v:
        if required:
            raise ValidationError("این فیلد الزامی است", details={key: "required"})
        return None
    if not lo <= len(v) <= hi:
        raise ValidationError(f"طول «{key}» باید بین {lo} و {hi} نویسه باشد", details={key: "length"})
    return v


def _national_id(data: dict, *, required: bool) -> str | None:
    raw = str(data.get("national_id") or "").translate(_DIGITS).strip()
    if not raw:
        if required:
            raise ValidationError("شناسهٔ ملی لازم است", details={"national_id": "required"})
        return None
    if not _NATIONAL_ID.match(raw):
        raise ValidationError("شناسهٔ ملی باید ۱۰ تا ۱۴ رقم باشد", details={"national_id": "format"})
    return raw


def _kind(data: dict) -> str:
    k = data.get("buyer_kind", "organization")
    if k not in BUYER_KINDS:
        raise ValidationError("نوع خریدار نامعتبر است", details={"buyer_kind": list(BUYER_KINDS)})
    return k


# ── invitations ─────────────────────────────────────────────────────────────

INVITE_TTL_DAYS = 14  # numbers get recycled: an old invitation must not hand an organization to a new SIM owner


def _add_member(conn, organization_id: int, user_id: int, role: str, actor: int | None) -> bool:
    """Creates the membership as 'invited': the person must accept it (sees who invited them and what it grants)."""
    row = conn.execute("SELECT id FROM organization_memberships WHERE organization_id=? AND user_id=?",
                       (organization_id, user_id)).fetchone()
    if row:
        return False
    conn.execute("INSERT INTO organization_memberships (organization_id, user_id, role, status, invited_by_user_id) "
                 "VALUES (?,?,?, 'invited', ?)", (organization_id, user_id, role, actor))
    return True


def _invite_cutoff() -> str:
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=INVITE_TTL_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def my_invitations(conn, *, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT m.id AS membership_id, m.role, o.id AS organization_id, o.display_name AS organization, o.buyer_kind, "
        "u.full_name AS invited_by FROM organization_memberships m JOIN organizations o ON o.id=m.organization_id "
        "LEFT JOIN users u ON u.id=m.invited_by_user_id WHERE m.user_id=? AND m.status='invited' AND o.status='active' "
        "ORDER BY m.id", (user_id,))]


def answer_invitation(conn, *, user_id: int, membership_id: int, accept: bool, ip_address: str | None = None) -> dict:
    m = conn.execute("SELECT id, organization_id, status FROM organization_memberships WHERE id=? AND user_id=?",
                     (membership_id, user_id)).fetchone()
    if m is None:
        raise NotFoundError("دعوت یافت نشد", code="invitation_not_found")
    if m["status"] != "invited":
        raise ConflictError("این دعوت قبلاً پاسخ داده شده است", code="invitation_answered")
    conn.execute("UPDATE organization_memberships SET status=? WHERE id=?", ("active" if accept else "inactive", membership_id))
    audit_service.record(conn, action="b2b.invitation_" + ("accepted" if accept else "declined"), entity_type="organization",
                         entity_id=int(m["organization_id"]), actor_user_id=user_id, ip_address=ip_address,
                         metadata={"membership_id": membership_id})
    return {"membership_id": membership_id, "status": "active" if accept else "declined"}


def invite(conn, *, organization_id: int, phone, role: str, actor_user_id: int | None) -> dict:
    if role not in ROLES:
        raise ValidationError("نقش نامعتبر است", details={"role": list(ROLES)})
    phone = normalize_phone(phone)
    stamp = _now()
    user = conn.execute("SELECT id FROM users WHERE phone_verified=? AND is_active=1", (phone,)).fetchone()
    existing = conn.execute("SELECT id, status FROM b2b_invites WHERE organization_id=? AND phone=?",
                            (organization_id, phone)).fetchone()
    if existing:
        conn.execute("UPDATE b2b_invites SET role=?, status=CASE WHEN status='revoked' THEN 'pending' ELSE status END "
                     "WHERE id=?", (role, existing["id"]))
        inv_id = int(existing["id"])
    else:
        inv_id = int(conn.execute("INSERT INTO b2b_invites (organization_id, phone, role, invited_by_user_id, created_at) "
                                  "VALUES (?,?,?,?,?)", (organization_id, phone, role, actor_user_id, stamp)).lastrowid)
    if user is not None:  # number already proven by its owner: membership now
        _add_member(conn, organization_id, int(user["id"]), role, actor_user_id)
        conn.execute("UPDATE b2b_invites SET status='claimed', claimed_user_id=?, claimed_at=? WHERE id=? AND status='pending'",
                     (int(user["id"]), stamp, inv_id))
    row = conn.execute("SELECT id, phone, role, status FROM b2b_invites WHERE id=?", (inv_id,)).fetchone()
    return {**dict(row), "phone": phone[:4] + "***" + phone[-4:]}


def claim_invites(conn, *, user_id: int, phone: str) -> list[int]:
    """Called once a number is verified for user_id: every fresh pending invite becomes an 'invited' membership,
    which the person then accepts or declines (my_invitations / answer_invitation)."""
    stamp = _now()
    joined = []
    for inv in conn.execute("SELECT i.id, i.organization_id, i.role, i.invited_by_user_id FROM b2b_invites i "
                            "JOIN organizations o ON o.id=i.organization_id "
                            "WHERE i.phone=? AND i.status='pending' AND o.status IN ('pending','active') AND i.created_at>?",
                            (phone, _invite_cutoff())).fetchall():
        _add_member(conn, int(inv["organization_id"]), user_id, inv["role"], inv["invited_by_user_id"])
        conn.execute("UPDATE b2b_invites SET status='claimed', claimed_user_id=?, claimed_at=? WHERE id=?",
                     (user_id, stamp, inv["id"]))
        audit_service.record(conn, action="b2b.invite_claimed", entity_type="organization",
                             entity_id=int(inv["organization_id"]), actor_user_id=user_id, metadata={"invite_id": inv["id"]})
        joined.append(int(inv["organization_id"]))
    return joined


# ── onboarding ──────────────────────────────────────────────────────────────

def _fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def onboard(conn: sqlite3.Connection, *, actor_user_id: int, data: dict, idempotency_key: str,
            ip_address: str | None = None) -> tuple[bool, dict]:
    """Open a business account in one step. Returns (created, account)."""
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValidationError("هدر Idempotency-Key لازم است", code="idempotency_key_required")
    if not isinstance(data, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    fp = _fingerprint(data)
    prev = conn.execute("SELECT fingerprint, organization_id FROM b2b_onboardings WHERE idempotency_key=?",
                        (idempotency_key,)).fetchone()
    if prev is not None:
        if prev["fingerprint"] != fp:
            raise ConflictError("این کلید یکتایی قبلاً با دادهٔ دیگری استفاده شده است", code="idempotency_conflict")
        return False, account(conn, int(prev["organization_id"]))

    kind = _kind(data)
    legal = _text(data, "legal_name", required=True)
    display = _text(data, "display_name", required=False) or legal
    nid = _national_id(data, required=True)
    license_no = _text(data, "business_license_no", required=(kind == "retailer"), lo=3, hi=40)
    city = _text(data, "city", required=False, hi=60)
    credit = data.get("credit") or {}
    contract = data.get("contract") or {}
    invites = data.get("invites") or []
    if not isinstance(credit, dict) or not isinstance(contract, dict) or not isinstance(invites, list):
        raise ValidationError("ساختار credit / contract / invites نامعتبر است")
    if len(invites) > MAX_INVITES:
        raise ValidationError(f"حداکثر {MAX_INVITES} دعوت در هر مرحله")
    if not any(isinstance(i, dict) and i.get("role") == "organization_admin" for i in invites):
        raise ValidationError("دست‌کم یک مدیر حساب (organization_admin) با شمارهٔ موبایل لازم است",
                              code="admin_invite_required")
    limit = credit.get("limit_minor", 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValidationError("سقف اعتبار باید عدد صحیح نامنفی (ریال) باشد", details={"credit.limit_minor": "int>=0"})
    app_id = data.get("application_id")
    if app_id is not None:
        app = conn.execute("SELECT id, status FROM b2b_applications WHERE id=?", (app_id,)).fetchone()
        if app is None:
            raise NotFoundError("درخواست یافت نشد", code="application_not_found")
        if app["status"] != "new":
            raise ConflictError("این درخواست قبلاً بررسی شده است", code="application_reviewed")

    stamp = _now()
    try:
        org_id = int(conn.execute(
            """INSERT INTO organizations (legal_name, display_name, national_id, status, credit_policy, credit_limit_minor,
                   billing_phone, billing_address, economic_code, created_by_user_id, buyer_kind, business_license_no, city)
               VALUES (?,?,?, 'active', 'employer_funded', ?,?,?,?,?,?,?,?)""",
            (legal, display, nid, limit, _text(data, "billing_phone", required=False, lo=5, hi=20),
             _text(data, "billing_address", required=False, hi=1000), _text(data, "economic_code", required=False, lo=5, hi=20),
             actor_user_id, kind, license_no, city)).lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ConflictError("سازمانی با این شناسهٔ ملی از قبل ثبت شده است", code="organization_exists") from exc

    if contract:
        title = _text(contract, "title", required=True, hi=200)
        ref = _text(contract, "reference", required=True, lo=1, hi=80)
        conn.execute("INSERT INTO organization_contracts (organization_id, title, contract_reference, start_date, end_date, notes, "
                     "status, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?, 'recorded', ?,?,?)",
                     (org_id, title, ref, contract.get("start_date"), contract.get("end_date"),
                      (contract.get("notes") or "")[:2000], actor_user_id, stamp, stamp))
    if limit > 0:
        ccs.create_contract(conn, organization_id=org_id, actor_user_id=actor_user_id,
                            idempotency_key=f"b2b:{idempotency_key}",
                            payload={"limit_minor": limit, "due_days": credit.get("due_days", 7),
                                     "statement_weekday": credit.get("statement_weekday", ccs.SATURDAY),
                                     "funder_type": "org", "contract_number": contract.get("reference"),
                                     "signed_by_name": credit.get("signed_by_name"),
                                     # shops start small and earn the full limit by paying on time (Udaan lesson)
                                     "ramp": credit.get("ramp", kind == "retailer"),
                                     "ramp_start_pct": credit.get("ramp_start_pct", 25)})
    for inv in invites:
        if not isinstance(inv, dict):
            raise ValidationError("هر دعوت باید {phone, role} باشد")
        invite(conn, organization_id=org_id, phone=inv.get("phone"), role=inv.get("role", "employee"),
               actor_user_id=actor_user_id)
    if app_id is not None:
        conn.execute("UPDATE b2b_applications SET status='approved', organization_id=?, reviewed_by_user_id=?, reviewed_at=? "
                     "WHERE id=?", (org_id, actor_user_id, stamp, app_id))
    conn.execute("INSERT INTO b2b_onboardings (idempotency_key, fingerprint, organization_id, created_at) VALUES (?,?,?,?)",
                 (idempotency_key, fp, org_id, stamp))
    audit_service.record(conn, action="b2b.onboarded", entity_type="organization", entity_id=org_id,
                         actor_user_id=actor_user_id, ip_address=ip_address,
                         metadata={"buyer_kind": kind,
                                   "credit_limit_minor": limit, "invites": len(invites)})
    return True, account(conn, org_id)


def account(conn, organization_id: int) -> dict:
    o = conn.execute("SELECT id, legal_name, display_name, national_id, status, buyer_kind, business_license_no, city, "
                     "credit_limit_minor FROM organizations WHERE id=?", (organization_id,)).fetchone()
    if o is None:
        raise NotFoundError("سازمان یافت نشد", code="organization_not_found")
    live = ccs.live_contract(conn, organization_id)
    cc = None
    if live is not None:
        cc = {"id": int(live["id"]), "reference": live["reference"], "status": live["status"],
              "limit_minor": int(live["limit_minor"]), "due_days": int(live["due_days"]),
              "outstanding_minor": ccs.outstanding_minor(conn, int(live["id"])),
              "overdue": ccs._has_overdue(conn, int(live["id"]))}
    contract = conn.execute("SELECT id, title, contract_reference, start_date, end_date, status FROM organization_contracts "
                            "WHERE organization_id=? ORDER BY id DESC LIMIT 1", (organization_id,)).fetchone()
    members = conn.execute("SELECT COUNT(*) FROM organization_memberships WHERE organization_id=? AND status='active'",
                           (organization_id,)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM b2b_invites WHERE organization_id=? AND status='pending'",
                           (organization_id,)).fetchone()[0]
    return {**dict(o), "contract": dict(contract) if contract else None, "credit_contract": cc,
            "active_members": members, "pending_invites": pending}


def overview(conn, *, buyer_kind: str | None = None) -> list[dict]:
    if buyer_kind is not None and buyer_kind not in BUYER_KINDS:
        raise ValidationError("نوع خریدار نامعتبر است")
    sql = "SELECT id FROM organizations WHERE provenance='real'" + (" AND buyer_kind=?" if buyer_kind else "") + " ORDER BY id DESC LIMIT 500"
    return [account(conn, int(r["id"])) for r in conn.execute(sql, (buyer_kind,) if buyer_kind else ())]


# ── public applications ─────────────────────────────────────────────────────

def submit_application(conn, *, data: dict, ip_address: str | None) -> dict:
    if not isinstance(data, dict):
        raise ValidationError("بدنهٔ درخواست نامعتبر است")
    kind = _kind(data)
    if data.get("privacy_consent") is not True:
        raise ValidationError("برای ثبت درخواست، رضایت به تماس و نگهداری اطلاعات لازم است", code="consent_required")
    phone = normalize_phone(data.get("phone"))
    day_ago = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if conn.execute("SELECT COUNT(*) FROM b2b_applications WHERE phone=? AND created_at>?", (phone, day_ago)).fetchone()[0] >= APPS_PER_PHONE_DAY:
        raise TooManyApplications("درخواست شما ثبت شده است؛ همکاران ما تماس می‌گیرند.")
    if ip_address and conn.execute("SELECT COUNT(*) FROM b2b_applications WHERE ip_address=? AND created_at>?",
                                   (ip_address, day_ago)).fetchone()[0] >= APPS_PER_IP_DAY:
        raise TooManyApplications("تعداد درخواست‌ها زیاد بوده؛ فردا دوباره امتحان کنید.")
    staff, monthly = data.get("staff_band"), data.get("monthly_band")
    if staff is not None and staff not in STAFF_BANDS:
        raise ValidationError("تعداد کارکنان نامعتبر است", details={"staff_band": list(STAFF_BANDS)})
    if monthly is not None and monthly not in MONTHLY_BANDS:
        raise ValidationError("حجم خرید ماهانه نامعتبر است", details={"monthly_band": list(MONTHLY_BANDS)})
    conn.execute(
        """INSERT INTO b2b_applications (buyer_kind, legal_name, national_id, business_license_no, contact_name, phone, city,
               staff_band, monthly_band, message, ip_address, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (kind, _text(data, "legal_name", required=True), _national_id(data, required=False),
         _text(data, "business_license_no", required=False, lo=3, hi=40), _text(data, "contact_name", required=True, hi=120),
         phone, _text(data, "city", required=False, hi=60), staff, monthly, _text(data, "message", required=False, lo=1, hi=1000),
         ip_address, _now()))
    return {"received": True}


APPLICATION_RETENTION_DAYS = 180


def purge_stale_applications(conn, *, now: _dt.datetime | None = None) -> int:
    """Rejected (or never-answered) leads hold personal data we no longer need: delete them after the retention period.
    Approved ones stay — they are the onboarding record of a live account."""
    cutoff = ((now or _dt.datetime.now(_dt.timezone.utc)) - _dt.timedelta(days=APPLICATION_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return conn.execute("DELETE FROM b2b_applications WHERE status IN ('rejected','new') AND created_at < ?", (cutoff,)).rowcount


def list_applications(conn, *, status: str = "new") -> list[dict]:
    if status not in ("new", "approved", "rejected"):
        raise ValidationError("وضعیت نامعتبر است")
    return [dict(r) for r in conn.execute(
        "SELECT id, buyer_kind, legal_name, national_id, business_license_no, contact_name, phone, city, staff_band, "
        "monthly_band, message, status, review_note, organization_id, created_at FROM b2b_applications WHERE status=? "
        "ORDER BY id DESC LIMIT 500", (status,))]


def reject_application(conn, *, application_id: int, actor_user_id: int, note) -> dict:
    note = (note or "").strip()[:500] if isinstance(note, str) else ""
    row = conn.execute("SELECT status FROM b2b_applications WHERE id=?", (application_id,)).fetchone()
    if row is None:
        raise NotFoundError("درخواست یافت نشد", code="application_not_found")
    if row["status"] != "new":
        raise ConflictError("این درخواست قبلاً بررسی شده است", code="application_reviewed")
    conn.execute("UPDATE b2b_applications SET status='rejected', review_note=?, reviewed_by_user_id=?, reviewed_at=? WHERE id=?",
                 (note or None, actor_user_id, _now(), application_id))
    return {"id": application_id, "status": "rejected"}
