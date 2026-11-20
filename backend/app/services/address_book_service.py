"""Customer address book (دفترچهٔ نشانی) on the existing ``addresses`` table (0001, + 0086).

* Owner-scoped: every read and write is ``WHERE user_id = ?``; another user's id is an ordinary 404.
* Persian (۰-۹) and Arabic-Indic (٠-٩) digits are normalized to ASCII before validation and storage.
* Mobile: Iranian mobile, stored as 09xxxxxxxxx (same rule as OTP login, ``otp_service.normalize_phone``).
* Postal code: exactly 10 digits (spaces and dashes are ignored).
* At most one default per user (partial unique index ``ux_addresses_one_default``); the first address is the
  default, and deleting the default promotes the most recently added remaining address.
* At checkout, ``address_id`` resolves to a snapshot of the saved address; the order keeps its own copy, so
  editing or deleting an address never changes a placed order.
"""
from __future__ import annotations

import re
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError

MAX_ADDRESSES = 20
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_POSTAL = re.compile(r"^\d{10}$")
_LIMITS = {"title": (1, 50), "recipient": (2, 100), "province": (2, 60), "city": (2, 60), "line1": (5, 300)}
_FA = {"title": "عنوان", "recipient": "نام گیرنده", "province": "استان", "city": "شهر", "line1": "نشانی",
       "phone": "موبایل", "postal_code": "کد پستی"}


def normalize_digits(value) -> str:
    return str(value or "").translate(DIGITS)


def normalize_postal_code(raw) -> str:
    s = re.sub(r"[\s\-]", "", normalize_digits(raw))
    if not _POSTAL.match(s):
        raise ValidationError("کد پستی باید ۱۰ رقم باشد", code="invalid_postal_code",
                              details={"postal_code": "کد پستی ۱۰ رقمی"})
    return s


def _text(data: dict, field: str, errors: dict) -> str:
    raw = data.get(field)
    value = " ".join(raw.split()) if isinstance(raw, str) else ""
    lo, hi = _LIMITS[field]
    if not lo <= len(value) <= hi:
        errors[field] = f"{_FA[field]} باید بین {lo} تا {hi} نویسه باشد"
    return value


def validate(data) -> dict:
    """Full validation of one address. Returns the cleaned fields or raises ValidationError with details."""
    from app.services.otp_service import normalize_phone
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    errors: dict[str, str] = {}
    cleaned = {f: _text(data, f, errors) for f in _LIMITS}
    try:
        cleaned["phone"] = normalize_phone(data.get("phone"))
    except ValidationError:
        errors["phone"] = "شمارهٔ موبایل معتبر نیست (مثل ۰۹۱۲۱۲۳۴۵۶۷)"
    try:
        cleaned["postal_code"] = normalize_postal_code(data.get("postal_code"))
    except ValidationError:
        errors["postal_code"] = "کد پستی باید ۱۰ رقم باشد"
    if errors:
        raise ValidationError("نشانی کامل یا معتبر نیست", code="invalid_address", details=errors)
    return cleaned


def _view(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "title": row["title"], "recipient": row["recipient"], "phone": row["phone"],
            "province": row["province"], "city": row["city"], "postal_code": row["postal_code"],
            "line1": row["line1"], "is_default": bool(row["is_default"]), "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def _get(conn: sqlite3.Connection, user_id: int, address_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM addresses WHERE id = ? AND user_id = ?", (address_id, user_id)).fetchone()
    if row is None:
        raise NotFoundError("نشانی یافت نشد", code="address_not_found")
    return row


def list_for_user(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return [_view(r) for r in conn.execute(
        "SELECT * FROM addresses WHERE user_id = ? ORDER BY is_default DESC, id DESC", (user_id,))]


def _make_default(conn: sqlite3.Connection, user_id: int, address_id: int) -> None:
    conn.execute("UPDATE addresses SET is_default = 0 WHERE user_id = ? AND is_default = 1 AND id <> ?",
                 (user_id, address_id))
    conn.execute("UPDATE addresses SET is_default = 1, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
                 (address_id, user_id))


def create(conn: sqlite3.Connection, *, user_id: int, data) -> dict:
    cleaned = validate(data)
    count = conn.execute("SELECT COUNT(*) FROM addresses WHERE user_id = ?", (user_id,)).fetchone()[0]
    if count >= MAX_ADDRESSES:
        raise ConflictError(f"حداکثر {MAX_ADDRESSES} نشانی می‌توانید ذخیره کنید", code="address_limit")
    cur = conn.execute(
        """INSERT INTO addresses (user_id, title, recipient, phone, province, city, postal_code, line1, is_default,
                                  updated_at) VALUES (?,?,?,?,?,?,?,?,0, datetime('now'))""",
        (user_id, cleaned["title"], cleaned["recipient"], cleaned["phone"], cleaned["province"], cleaned["city"],
         cleaned["postal_code"], cleaned["line1"]))
    address_id = int(cur.lastrowid)
    if count == 0 or (isinstance(data, dict) and data.get("is_default") is True):
        _make_default(conn, user_id, address_id)
    return _view(_get(conn, user_id, address_id))


def update(conn: sqlite3.Connection, *, user_id: int, address_id: int, data) -> dict:
    current = _get(conn, user_id, address_id)
    if not isinstance(data, dict):
        raise ValidationError("بدنه درخواست باید JSON باشد")
    merged = {k: current[k] for k in ("title", "recipient", "phone", "province", "city", "postal_code", "line1")}
    merged.update({k: v for k, v in data.items() if k in merged})
    cleaned = validate(merged)
    conn.execute(
        """UPDATE addresses SET title = ?, recipient = ?, phone = ?, province = ?, city = ?, postal_code = ?, line1 = ?,
                  updated_at = datetime('now') WHERE id = ? AND user_id = ?""",
        (cleaned["title"], cleaned["recipient"], cleaned["phone"], cleaned["province"], cleaned["city"],
         cleaned["postal_code"], cleaned["line1"], address_id, user_id))
    if data.get("is_default") is True:
        _make_default(conn, user_id, address_id)
    return _view(_get(conn, user_id, address_id))


def set_default(conn: sqlite3.Connection, *, user_id: int, address_id: int) -> dict:
    _get(conn, user_id, address_id)
    _make_default(conn, user_id, address_id)
    return _view(_get(conn, user_id, address_id))


def delete(conn: sqlite3.Connection, *, user_id: int, address_id: int) -> None:
    row = _get(conn, user_id, address_id)
    conn.execute("DELETE FROM addresses WHERE id = ? AND user_id = ?", (address_id, user_id))
    if row["is_default"]:
        nxt = conn.execute("SELECT id FROM addresses WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if nxt is not None:
            _make_default(conn, user_id, int(nxt["id"]))


def as_shipping_address(conn: sqlite3.Connection, *, user_id: int, address_id) -> dict:
    """The checkout shape (recipient_name, recipient_phone, province, city, line1, postal_code) of a saved address."""
    if isinstance(address_id, bool) or not isinstance(address_id, int):
        raise ValidationError("شناسهٔ نشانی باید عدد صحیح باشد", code="invalid_address_id")
    row = _get(conn, user_id, address_id)
    return {"recipient_name": row["recipient"], "recipient_phone": row["phone"], "province": row["province"],
            "city": row["city"], "line1": row["line1"], "postal_code": row["postal_code"]}
