"""Retail network (شبکهٔ فروشگاه‌های زنجیره‌ای و طرف قرارداد).

Chains, their sectors and their branches across Iran's 31 provinces, each with a contract status.

Visibility rule (the one invariant every public query enforces through ``_PUBLIC``):
a branch is public only when the branch AND its chain are ``active`` and the chain's provenance is ``real``.
Prospects, negotiations, paused and ended contracts stay in the admin panel.

Data rule (AGENTS.md #9): branch rows are real business data. Every branch must name where it came from
(``data_source`` + ``source_reference``); nothing is generated or guessed here. The CSV import validates and
reports per-row errors instead of "fixing" values.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import re
import sqlite3

from app.core.errors import ConflictError, NotFoundError, ValidationError

STATUSES = ("prospect", "negotiating", "active", "paused", "ended")
DATA_SOURCES = ("chain_file", "contract", "chain_website", "field_visit")
MAX_IMPORT_ROWS = 5000
# Generous bounding box around Iran; rejects swapped lat/lng and obviously foreign points.
_LAT = (24.0, 40.5)
_LNG = (43.5, 64.0)
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PHONE = re.compile(r"^\+?[0-9]{4,15}$")
_URL = re.compile(r"^https?://[^\s]{3,200}$")

_PUBLIC = "b.contract_status='active' AND c.contract_status='active' AND c.provenance='real'"

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def normalize_fa(value) -> str:
    """Unify Arabic/Persian letters and whitespace so «تهران»/«تهران » and ي/ی, ك/ک match."""
    s = str(value or "").replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("‌", " ")
    return re.sub(r"\s+", " ", s).strip()


def _text(d: dict, key: str, limit: int, *, required: bool = False) -> str | None:
    v = d.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ValidationError(f"«{key}» الزامی است", code="missing_field", details={"field": key})
        return None
    if not isinstance(v, str):
        raise ValidationError(f"«{key}» باید متن باشد", details={"field": key})
    v = normalize_fa(v)
    if len(v) > limit:
        raise ValidationError(f"«{key}» حداکثر {limit} نویسه است", details={"field": key})
    return v


def _status(v, field: str = "contract_status") -> str:
    if v not in STATUSES:
        raise ValidationError(f"«{field}» باید یکی از {', '.join(STATUSES)} باشد", code="invalid_status",
                              details={"field": field})
    return v


def _num(v) -> float | None:
    """Coordinates are stored as decimal TEXT (no float columns); the API returns them as numbers."""
    return None if v in (None, "") else float(v)


def _coord(v, rng: tuple[float, float], field: str) -> str | None:
    if v is None or v == "":
        return None
    try:
        f = float(str(v).translate(_FA_DIGITS).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"«{field}» عدد نیست", code="invalid_coordinate", details={"field": field}) from None
    if not rng[0] <= f <= rng[1]:
        raise ValidationError(f"«{field}» خارج از محدودهٔ ایران است", code="invalid_coordinate", details={"field": field})
    return f"{f:.6f}"


# ---------------------------------------------------------------- reference data

def resolve_province(conn: sqlite3.Connection, value) -> sqlite3.Row:
    v = normalize_fa(value)
    if v.startswith("استان "):
        v = v[6:]
    row = conn.execute("SELECT * FROM network_provinces WHERE slug=? OR name_fa=?", (v.lower(), v)).fetchone()
    if row is None:
        raise ValidationError(f"استان «{value}» شناخته نشد", code="unknown_province", details={"field": "province"})
    return row


def get_or_create_city(conn: sqlite3.Connection, province_id: int, name) -> int:
    n = normalize_fa(name)
    if not n or len(n) > 80:
        raise ValidationError("نام شهر نامعتبر است", details={"field": "city"})
    row = conn.execute("SELECT id FROM network_cities WHERE province_id=? AND name_fa=?", (province_id, n)).fetchone()
    if row:
        return int(row["id"])
    return int(conn.execute("INSERT INTO network_cities (province_id, name_fa, created_at) VALUES (?,?,?)",
                            (province_id, n, _now())).lastrowid)


def list_sectors(conn: sqlite3.Connection, *, include_inactive: bool = False) -> list[dict]:
    where = "" if include_inactive else "WHERE is_active=1"
    return [{"id": r["id"], "slug": r["slug"], "name": r["name_fa"], "active": bool(r["is_active"])}
            for r in conn.execute(f"SELECT * FROM chain_sectors {where} ORDER BY sort_order, id").fetchall()]


def create_sector(conn: sqlite3.Connection, d: dict) -> dict:
    slug = (d.get("slug") or "").strip().lower()
    if not _SLUG.match(slug) or len(slug) > 60:
        raise ValidationError("شناسهٔ لاتین حوزه نامعتبر است (مثل dried-fruit)", details={"field": "slug"})
    name = _text(d, "name", 80, required=True)
    if conn.execute("SELECT 1 FROM chain_sectors WHERE slug=? OR name_fa=?", (slug, name)).fetchone():
        raise ConflictError("این حوزه از قبل هست", code="sector_exists")
    order = (conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM chain_sectors").fetchone()["n"])
    sid = conn.execute("INSERT INTO chain_sectors (slug, name_fa, sort_order, created_at) VALUES (?,?,?,?)",
                       (slug, name, order, _now())).lastrowid
    return {"id": int(sid), "slug": slug, "name": name, "active": True}


def set_sector_active(conn: sqlite3.Connection, sector_id: int, active) -> None:
    if type(active) is not bool:
        raise ValidationError("«active» باید true یا false باشد")
    if conn.execute("UPDATE chain_sectors SET is_active=? WHERE id=?", (int(active), sector_id)).rowcount == 0:
        raise NotFoundError("حوزه یافت نشد")


def _sector_ids(conn: sqlite3.Connection, values) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(x, str) for x in values):
        raise ValidationError("«sectors» باید فهرست شناسهٔ حوزه‌ها باشد", details={"field": "sectors"})
    ids = []
    for slug in dict.fromkeys(x.strip().lower() for x in values):
        row = conn.execute("SELECT id FROM chain_sectors WHERE slug=?", (slug,)).fetchone()
        if row is None:
            raise ValidationError(f"حوزهٔ «{slug}» تعریف نشده است", code="unknown_sector", details={"field": "sectors"})
        ids.append(int(row["id"]))
    return ids


# ---------------------------------------------------------------- chains (admin)

def _chain_sectors(conn: sqlite3.Connection, chain_id: int) -> list[dict]:
    return [{"slug": r["slug"], "name": r["name_fa"]} for r in conn.execute(
        "SELECT s.slug, s.name_fa FROM retail_chain_sectors x JOIN chain_sectors s ON s.id=x.sector_id "
        "WHERE x.chain_id=? ORDER BY s.sort_order", (chain_id,)).fetchall()]


def _chain_admin_view(conn: sqlite3.Connection, r) -> dict:
    counts = {s: 0 for s in STATUSES}
    for row in conn.execute("SELECT contract_status, COUNT(*) AS n FROM chain_branches WHERE chain_id=? "
                            "GROUP BY contract_status", (r["id"],)).fetchall():
        counts[row["contract_status"]] = int(row["n"])
    provinces = conn.execute("SELECT COUNT(DISTINCT province_id) AS n FROM chain_branches WHERE chain_id=?",
                             (r["id"],)).fetchone()["n"]
    return {"id": r["id"], "slug": r["slug"], "name": r["name_fa"], "brand_name": r["brand_name"],
            "website": r["website"], "contract_status": r["contract_status"],
            "contract_signed_on": r["contract_signed_on"], "contract_reference": r["contract_reference"],
            "owner_user_id": r["owner_user_id"], "supplier_id": r["supplier_id"], "provenance": r["provenance"],
            "notes": r["notes"], "sectors": _chain_sectors(conn, r["id"]), "branch_counts": counts,
            "province_count": int(provinces), "created_at": r["created_at"], "updated_at": r["updated_at"]}


def admin_list_chains(conn: sqlite3.Connection, *, status: str | None = None, q: str | None = None) -> list[dict]:
    where, args = [], []
    if status:
        where.append("contract_status=?"); args.append(_status(status, "status"))
    if q:
        where.append("(name_fa LIKE ? OR brand_name LIKE ? OR slug LIKE ?)")
        like = f"%{normalize_fa(q)[:60]}%"
        args += [like, like, like]
    sql = "SELECT * FROM retail_chains" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY name_fa LIMIT 500"
    return [_chain_admin_view(conn, r) for r in conn.execute(sql, args).fetchall()]


def _chain_fields(conn: sqlite3.Connection, d: dict, *, creating: bool) -> dict:
    allowed = {"slug", "name", "brand_name", "website", "contract_status", "contract_signed_on",
               "contract_reference", "owner_user_id", "supplier_id", "notes", "sectors", "provenance"}
    extra = set(d) - allowed
    if extra:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(extra)})
    out: dict = {}
    if creating or "slug" in d:
        slug = (d.get("slug") or "").strip().lower() if isinstance(d.get("slug"), str) else ""
        if not _SLUG.match(slug) or len(slug) > 60:
            raise ValidationError("شناسهٔ لاتین زنجیره نامعتبر است (مثل ofogh-koorosh)", details={"field": "slug"})
        out["slug"] = slug
    if creating or "name" in d:
        out["name_fa"] = _text(d, "name", 120, required=True)
    for key, col, lim in (("brand_name", "brand_name", 120), ("contract_reference", "contract_reference", 120),
                          ("notes", "notes", 2000)):
        if key in d:
            out[col] = _text(d, key, lim)
    if "website" in d:
        w = d.get("website")
        if w not in (None, "") and not (isinstance(w, str) and _URL.match(w.strip())):
            raise ValidationError("نشانی وبسایت باید با http:// یا https:// شروع شود", details={"field": "website"})
        out["website"] = w.strip() if w else None
    if "contract_status" in d or creating:
        out["contract_status"] = _status(d.get("contract_status", "prospect"))
    if "contract_signed_on" in d:
        v = d.get("contract_signed_on")
        if v not in (None, ""):
            try:
                _dt.date.fromisoformat(str(v))
            except ValueError:
                raise ValidationError("تاریخ قرارداد باید YYYY-MM-DD (میلادی) باشد", details={"field": "contract_signed_on"}) from None
        out["contract_signed_on"] = v or None
    for key in ("owner_user_id", "supplier_id"):
        if key in d:
            v = d.get(key)
            if v is not None and type(v) is not int:
                raise ValidationError(f"«{key}» باید عدد باشد", details={"field": key})
            table = "users" if key == "owner_user_id" else "suppliers"
            if v is not None and not conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (v,)).fetchone():
                raise ValidationError(f"«{key}» یافت نشد", details={"field": key})
            out[key] = v
    if "provenance" in d:
        if d["provenance"] not in ("real", "test"):
            raise ValidationError("«provenance» باید real یا test باشد", details={"field": "provenance"})
        out["provenance"] = d["provenance"]
    return out


def _require_contract_evidence(conn: sqlite3.Connection, chain_id: int) -> None:
    r = conn.execute("SELECT contract_status, contract_reference, contract_signed_on FROM retail_chains WHERE id=?",
                     (chain_id,)).fetchone()
    if r["contract_status"] == "active" and not (r["contract_reference"] or r["contract_signed_on"]):
        raise ValidationError("برای فعال کردن زنجیره، شمارهٔ قرارداد یا تاریخ امضا را ثبت کنید",
                              code="contract_evidence_required")


def create_chain(conn: sqlite3.Connection, d: dict, *, actor_user_id: int | None = None) -> dict:
    f = _chain_fields(conn, d, creating=True)
    if conn.execute("SELECT 1 FROM retail_chains WHERE slug=?", (f["slug"],)).fetchone():
        raise ConflictError("زنجیره‌ای با این شناسه هست", code="chain_exists")
    sectors = _sector_ids(conn, d.get("sectors"))
    stamp = _now()
    f.setdefault("owner_user_id", actor_user_id)
    cols = list(f) + ["created_at", "updated_at"]
    cid = int(conn.execute(f"INSERT INTO retail_chains ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           [*f.values(), stamp, stamp]).lastrowid)
    for sid in sectors:
        conn.execute("INSERT INTO retail_chain_sectors (chain_id, sector_id) VALUES (?,?)", (cid, sid))
    _require_contract_evidence(conn, cid)
    return _chain_admin_view(conn, conn.execute("SELECT * FROM retail_chains WHERE id=?", (cid,)).fetchone())


def update_chain(conn: sqlite3.Connection, chain_id: int, d: dict) -> dict:
    if not conn.execute("SELECT 1 FROM retail_chains WHERE id=?", (chain_id,)).fetchone():
        raise NotFoundError("زنجیره یافت نشد")
    f = _chain_fields(conn, d, creating=False)
    if "slug" in f and conn.execute("SELECT 1 FROM retail_chains WHERE slug=? AND id<>?", (f["slug"], chain_id)).fetchone():
        raise ConflictError("زنجیره‌ای با این شناسه هست", code="chain_exists")
    if f:
        conn.execute(f"UPDATE retail_chains SET {', '.join(f'{k}=?' for k in f)}, updated_at=? WHERE id=?",
                     [*f.values(), _now(), chain_id])
    if "sectors" in d:
        ids = _sector_ids(conn, d["sectors"])
        conn.execute("DELETE FROM retail_chain_sectors WHERE chain_id=?", (chain_id,))
        for sid in ids:
            conn.execute("INSERT INTO retail_chain_sectors (chain_id, sector_id) VALUES (?,?)", (chain_id, sid))
    _require_contract_evidence(conn, chain_id)
    return _chain_admin_view(conn, conn.execute("SELECT * FROM retail_chains WHERE id=?", (chain_id,)).fetchone())


def _chain_by_slug(conn: sqlite3.Connection, slug) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM retail_chains WHERE slug=?", (str(slug or "").strip().lower(),)).fetchone()
    if row is None:
        raise ValidationError(f"زنجیرهٔ «{slug}» تعریف نشده است", code="unknown_chain", details={"field": "chain_slug"})
    return row


# ---------------------------------------------------------------- branches (admin)

def _branch_view(r, *, admin: bool) -> dict:
    d = {"id": r["id"], "title": r["title"] or r["chain_name"], "chain": {"slug": r["chain_slug"], "name": r["chain_name"]},
         "province": {"slug": r["province_slug"], "name": r["province_name"]}, "city": r["city_name"],
         "district": r["district"], "address": r["address"], "latitude": _num(r["latitude"]), "longitude": _num(r["longitude"]),
         "phone": r["phone"]}
    if admin:
        d.update({"branch_code": r["branch_code"], "contract_status": r["contract_status"],
                  "chain_contract_status": r["chain_status"], "supplier_location_id": r["supplier_location_id"],
                  "data_source": r["data_source"], "source_reference": r["source_reference"],
                  "public": r["contract_status"] == "active" and r["chain_status"] == "active",
                  "updated_at": r["updated_at"]})
    return d


_BRANCH_SELECT = (
    "SELECT b.*, c.slug AS chain_slug, c.name_fa AS chain_name, c.contract_status AS chain_status, "
    "p.slug AS province_slug, p.name_fa AS province_name, ci.name_fa AS city_name "
    "FROM chain_branches b JOIN retail_chains c ON c.id=b.chain_id JOIN network_provinces p ON p.id=b.province_id "
    "LEFT JOIN network_cities ci ON ci.id=b.city_id")


def _branch_fields(conn: sqlite3.Connection, d: dict, *, creating: bool) -> dict:
    allowed = {"chain_slug", "branch_code", "title", "province", "city", "district", "address", "latitude",
               "longitude", "phone", "contract_status", "supplier_location_id", "data_source", "source_reference"}
    extra = set(d) - allowed
    if extra:
        raise ValidationError("فیلد ناشناخته", details={"fields": sorted(extra)})
    out: dict = {}
    if creating:
        out["chain_id"] = int(_chain_by_slug(conn, d.get("chain_slug"))["id"])
    if creating or "branch_code" in d:
        out["branch_code"] = _text(d, "branch_code", 60, required=True)
    for key, lim in (("title", 120), ("district", 80), ("address", 300)):
        if key in d:
            out[key] = _text(d, key, lim)
    province = None
    if creating or "province" in d:
        province = resolve_province(conn, d.get("province"))
        out["province_id"] = int(province["id"])
    if creating or "city" in d or province is not None:
        pid = out.get("province_id")
        if pid is None:
            raise ValidationError("برای تغییر شهر، استان را هم بفرستید", details={"field": "province"})
        out["city_id"] = get_or_create_city(conn, pid, _text(d, "city", 80, required=True))
    if "latitude" in d or "longitude" in d or creating:
        lat = _coord(d.get("latitude"), _LAT, "latitude")
        lng = _coord(d.get("longitude"), _LNG, "longitude")
        if (lat is None) != (lng is None):
            raise ValidationError("عرض و طول جغرافیایی باید با هم ثبت شوند", code="invalid_coordinate")
        out["latitude"], out["longitude"] = lat, lng
    if "phone" in d:
        p = d.get("phone")
        p = str(p).translate(_FA_DIGITS).replace(" ", "").replace("-", "") if p not in (None, "") else None
        if p is not None and not _PHONE.match(p):
            raise ValidationError("تلفن شعبه نامعتبر است", details={"field": "phone"})
        out["phone"] = p
    if creating or "contract_status" in d:
        out["contract_status"] = _status(d.get("contract_status", "prospect"))
    if "supplier_location_id" in d:
        v = d.get("supplier_location_id")
        if v is not None and (type(v) is not int or not conn.execute(
                "SELECT 1 FROM supplier_locations WHERE id=?", (v,)).fetchone()):
            raise ValidationError("محل فروشنده یافت نشد", details={"field": "supplier_location_id"})
        out["supplier_location_id"] = v
    if creating or "data_source" in d:
        if d.get("data_source") not in DATA_SOURCES:
            raise ValidationError(f"منبع داده باید یکی از {', '.join(DATA_SOURCES)} باشد", code="missing_source",
                                  details={"field": "data_source"})
        out["data_source"] = d["data_source"]
    if creating or "source_reference" in d:
        out["source_reference"] = _text(d, "source_reference", 200, required=True)
    return out


def admin_list_branches(conn: sqlite3.Connection, *, chain: str | None = None, province: str | None = None,
                        status: str | None = None, limit: int = 500) -> list[dict]:
    where, args = [], []
    if chain:
        where.append("c.slug=?"); args.append(chain.strip().lower())
    if province:
        where.append("b.province_id=?"); args.append(resolve_province(conn, province)["id"])
    if status:
        where.append("b.contract_status=?"); args.append(_status(status, "status"))
    sql = _BRANCH_SELECT + (f" WHERE {' AND '.join(where)}" if where else "") + \
        " ORDER BY p.sort_order, ci.name_fa, b.id LIMIT ?"
    return [_branch_view(r, admin=True) for r in conn.execute(sql, [*args, max(1, min(limit, 2000))]).fetchall()]


def create_branch(conn: sqlite3.Connection, d: dict) -> dict:
    f = _branch_fields(conn, d, creating=True)
    if conn.execute("SELECT 1 FROM chain_branches WHERE chain_id=? AND branch_code=?",
                    (f["chain_id"], f["branch_code"])).fetchone():
        raise ConflictError("این کد شعبه برای این زنجیره ثبت شده است", code="branch_exists")
    stamp = _now()
    cols = list(f) + ["created_at", "updated_at"]
    bid = conn.execute(f"INSERT INTO chain_branches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       [*f.values(), stamp, stamp]).lastrowid
    return _branch_view(conn.execute(_BRANCH_SELECT + " WHERE b.id=?", (bid,)).fetchone(), admin=True)


def update_branch(conn: sqlite3.Connection, branch_id: int, d: dict) -> dict:
    if "chain_slug" in d:
        raise ValidationError("انتقال شعبه به زنجیرهٔ دیگر مجاز نیست؛ شعبهٔ تازه ثبت کنید", details={"field": "chain_slug"})
    row = conn.execute("SELECT * FROM chain_branches WHERE id=?", (branch_id,)).fetchone()
    if row is None:
        raise NotFoundError("شعبه یافت نشد")
    if "city" in d and "province" not in d:
        d = {**d, "province": conn.execute("SELECT slug FROM network_provinces WHERE id=?",
                                           (row["province_id"],)).fetchone()["slug"]}
    f = _branch_fields(conn, d, creating=False)
    if "branch_code" in f and conn.execute("SELECT 1 FROM chain_branches WHERE chain_id=? AND branch_code=? AND id<>?",
                                           (row["chain_id"], f["branch_code"], branch_id)).fetchone():
        raise ConflictError("این کد شعبه برای این زنجیره ثبت شده است", code="branch_exists")
    if f:
        conn.execute(f"UPDATE chain_branches SET {', '.join(f'{k}=?' for k in f)}, updated_at=? WHERE id=?",
                     [*f.values(), _now(), branch_id])
    return _branch_view(conn.execute(_BRANCH_SELECT + " WHERE b.id=?", (branch_id,)).fetchone(), admin=True)


# ---------------------------------------------------------------- CSV import (admin)

CSV_COLUMNS = ("chain_slug", "branch_code", "title", "province", "city", "district", "address", "latitude",
               "longitude", "phone", "contract_status", "data_source", "source_reference")


def _in_savepoint(conn: sqlite3.Connection, keep: bool, fn) -> None:
    """Run one row atomically: a failing row leaves nothing behind; a dry run (keep=False) undoes a good row too."""
    conn.execute("SAVEPOINT net_row")
    try:
        fn()
    except BaseException:
        conn.execute("ROLLBACK TO SAVEPOINT net_row")
        conn.execute("RELEASE SAVEPOINT net_row")
        raise
    if not keep:
        conn.execute("ROLLBACK TO SAVEPOINT net_row")
    conn.execute("RELEASE SAVEPOINT net_row")


def import_branches_csv(conn: sqlite3.Connection, text: str, *, commit: bool) -> dict:
    """Upsert branches keyed by (chain_slug, branch_code) and return per-row results.
    commit=False is a dry run: every row is validated for real and then undone. Bad rows never block good ones."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("فایل CSV خالی است", code="empty_file")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in ("chain_slug", "branch_code", "province", "city", "data_source", "source_reference")
               if c not in header]
    if missing:
        raise ValidationError("ستون‌های لازم در فایل نیست", code="missing_columns", details={"columns": missing})
    unknown = [h for h in header if h not in CSV_COLUMNS]
    if unknown:
        raise ValidationError("ستون ناشناخته در فایل", code="unknown_columns", details={"columns": unknown})
    results, created, updated, seen = [], 0, 0, set()
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_IMPORT_ROWS:
            raise ValidationError(f"حداکثر {MAX_IMPORT_ROWS} ردیف در هر فایل", code="too_many_rows")
        row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        row = {k: v for k, v in row.items() if v not in (None, "")}
        key = (str(row.get("chain_slug", "")).lower(), normalize_fa(row.get("branch_code")))
        try:
            if key in seen:
                raise ValidationError("این شعبه در همین فایل تکرار شده است", code="duplicate_row")
            seen.add(key)
            chain = _chain_by_slug(conn, row.get("chain_slug"))
            existing = conn.execute("SELECT id FROM chain_branches WHERE chain_id=? AND branch_code=?",
                                    (chain["id"], key[1])).fetchone()
            if existing:
                fields = {k: v for k, v in row.items() if k != "chain_slug"}
                _in_savepoint(conn, commit, lambda: update_branch(conn, int(existing["id"]), fields))
                updated += 1
                results.append({"line": n, "action": "update", "branch_code": key[1]})
            else:
                _in_savepoint(conn, commit, lambda: create_branch(conn, row))
                created += 1
                results.append({"line": n, "action": "create", "branch_code": key[1]})
        except (ValidationError, ConflictError, NotFoundError) as e:
            results.append({"line": n, "action": "error", "branch_code": key[1] or None,
                            "error": str(getattr(e, "message", e)), "code": getattr(e, "code", None)})
    errors = [r for r in results if r["action"] == "error"]
    return {"committed": commit, "rows": len(results), "created": created, "updated": updated,
            "errors": len(errors), "results": results[:1000]}


# ---------------------------------------------------------------- public

def public_network(conn: sqlite3.Connection, *, province: str | None = None, sector: str | None = None,
                   chain: str | None = None, city: str | None = None, limit: int = 500) -> dict:
    where, args = [_PUBLIC], []
    if province:
        where.append("b.province_id=?"); args.append(resolve_province(conn, province)["id"])
    if city:
        where.append("ci.name_fa=?"); args.append(normalize_fa(city)[:80])
    if chain:
        where.append("c.slug=?"); args.append(chain.strip().lower()[:60])
    if sector:
        where.append("EXISTS (SELECT 1 FROM retail_chain_sectors x JOIN chain_sectors s ON s.id=x.sector_id "
                     "WHERE x.chain_id=c.id AND s.slug=? AND s.is_active=1)")
        args.append(sector.strip().lower()[:60])
    sql = _BRANCH_SELECT + f" WHERE {' AND '.join(where)} ORDER BY p.sort_order, ci.name_fa, c.name_fa, b.id LIMIT ?"
    lim = max(1, min(int(limit), 1000))
    rows = conn.execute(sql, [*args, lim + 1]).fetchall()
    return {"items": [_branch_view(r, admin=False) for r in rows[:lim]], "truncated": len(rows) > lim}


def public_coverage(conn: sqlite3.Connection, *, sector: str | None = None) -> dict:
    sec_join, args = "", []
    if sector:
        sec_join = ("AND EXISTS (SELECT 1 FROM retail_chain_sectors x JOIN chain_sectors s ON s.id=x.sector_id "
                    "WHERE x.chain_id=c.id AND s.slug=? AND s.is_active=1)")
        args.append(sector.strip().lower()[:60])
    rows = conn.execute(
        "SELECT p.slug, p.name_fa, p.capital_fa, p.center_lat, p.center_lng, "
        "COUNT(b.id) AS branches, COUNT(DISTINCT b.chain_id) AS chains, COUNT(DISTINCT b.city_id) AS cities "
        "FROM network_provinces p LEFT JOIN chain_branches b ON b.province_id=p.id "
        f"AND b.chain_id IN (SELECT c.id FROM retail_chains c WHERE c.contract_status='active' AND c.provenance='real' {sec_join}) "
        "AND b.contract_status='active' "
        "GROUP BY p.id, p.slug, p.name_fa, p.capital_fa, p.center_lat, p.center_lng, p.sort_order ORDER BY p.sort_order",
        args).fetchall()
    provinces = [{"slug": r["slug"], "name": r["name_fa"], "capital": r["capital_fa"],
                  "center": [_num(r["center_lat"]), _num(r["center_lng"])], "branches": int(r["branches"]),
                  "chains": int(r["chains"]), "cities": int(r["cities"]), "covered": int(r["branches"]) > 0}
                 for r in rows]
    return {"provinces": provinces,
            "totals": {"provinces_covered": sum(1 for p in provinces if p["covered"]),
                       "provinces": len(provinces), "branches": sum(p["branches"] for p in provinces)},
            "center_note": "مختصات مرکز استان تقریبی و مربوط به مرکز استان است، نه مرز یا نشانی."}


def public_chains(conn: sqlite3.Connection, *, sector: str | None = None) -> list[dict]:
    where, args = ["c.contract_status='active'", "c.provenance='real'"], []
    if sector:
        where.append("EXISTS (SELECT 1 FROM retail_chain_sectors x JOIN chain_sectors s ON s.id=x.sector_id "
                     "WHERE x.chain_id=c.id AND s.slug=? AND s.is_active=1)")
        args.append(sector.strip().lower()[:60])
    rows = conn.execute(
        "SELECT c.id, c.slug, c.name_fa, c.brand_name, c.website, "
        "(SELECT COUNT(*) FROM chain_branches b WHERE b.chain_id=c.id AND b.contract_status='active') AS branches, "
        "(SELECT COUNT(DISTINCT b.province_id) FROM chain_branches b WHERE b.chain_id=c.id AND b.contract_status='active') AS provinces "
        f"FROM retail_chains c WHERE {' AND '.join(where)} ORDER BY c.name_fa", args).fetchall()
    return [{"slug": r["slug"], "name": r["name_fa"], "brand_name": r["brand_name"], "website": r["website"],
             "sectors": _chain_sectors(conn, r["id"]), "branches": int(r["branches"]), "provinces": int(r["provinces"])}
            for r in rows]


def public_chain(conn: sqlite3.Connection, slug: str) -> dict:
    r = conn.execute("SELECT * FROM retail_chains WHERE slug=? AND contract_status='active' AND provenance='real'",
                     (str(slug).strip().lower()[:60],)).fetchone()
    if r is None:
        raise NotFoundError("زنجیره یافت نشد")
    net = public_network(conn, chain=r["slug"], limit=1000)
    return {"slug": r["slug"], "name": r["name_fa"], "brand_name": r["brand_name"], "website": r["website"],
            "sectors": _chain_sectors(conn, r["id"]), "branches": net["items"], "truncated": net["truncated"]}


def public_province(conn: sqlite3.Connection, slug: str) -> dict:
    p = conn.execute("SELECT * FROM network_provinces WHERE slug=?", (str(slug).strip().lower()[:60],)).fetchone()
    if p is None:
        raise NotFoundError("استان یافت نشد")
    net = public_network(conn, province=p["slug"], limit=1000)
    cities: dict[str, int] = {}
    for b in net["items"]:
        cities[b["city"] or "—"] = cities.get(b["city"] or "—", 0) + 1
    return {"slug": p["slug"], "name": p["name_fa"], "capital": p["capital_fa"],
            "center": [_num(p["center_lat"]), _num(p["center_lng"])], "branches": net["items"], "truncated": net["truncated"],
            "cities": [{"name": k, "branches": v} for k, v in sorted(cities.items(), key=lambda kv: -kv[1])]}


# ---------------------------------------------------------------- chain → platform supplier locations (admin)

def sync_chain_locations(conn: sqlite3.Connection, chain_id: int) -> dict:
    """Give each active branch of a chain a supplier location, so the existing fulfillment engine
    (same city → same province → national) and the in-person pickup code can use the branch.

    New locations are created INACTIVE with every delivery capability off: nothing becomes orderable
    until an admin confirms with the chain which branches deliver, ship or serve walk-ins.
    Idempotent: branches already linked to a location are left alone.
    """
    chain = conn.execute("SELECT * FROM retail_chains WHERE id=?", (chain_id,)).fetchone()
    if chain is None:
        raise NotFoundError("زنجیره یافت نشد")
    if chain["supplier_id"] is None:
        raise ValidationError("اول زنجیره را به یک فروشندهٔ پلتفرم وصل کنید (supplier_id)", code="chain_not_supplier")
    if chain["contract_status"] != "active":
        raise ValidationError("فقط زنجیرهٔ دارای قرارداد فعال", code="chain_not_active")
    rows = conn.execute(_BRANCH_SELECT + " WHERE b.chain_id=? AND b.contract_status='active' "
                        "AND b.supplier_location_id IS NULL ORDER BY b.id", (chain_id,)).fetchall()
    stamp = _now()
    created = []
    for r in rows:
        loc = conn.execute(
            "INSERT INTO supplier_locations (supplier_id, province, city, district, address, latitude, longitude, "
            "status, can_pickup, can_local_delivery, can_intercity_shipping, public_title, public_phone, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'inactive', 0, 0, 0, ?,?,?,?)",
            (chain["supplier_id"], r["province_name"], r["city_name"], r["district"], r["address"], r["latitude"],
             r["longitude"], r["title"] or chain["name_fa"], r["phone"], stamp, stamp)).lastrowid
        conn.execute("UPDATE chain_branches SET supplier_location_id=?, updated_at=? WHERE id=?", (loc, stamp, r["id"]))
        created.append({"branch_id": r["id"], "branch_code": r["branch_code"], "supplier_location_id": int(loc)})
    linked = conn.execute("SELECT COUNT(*) AS n FROM chain_branches WHERE chain_id=? AND supplier_location_id IS NOT NULL",
                          (chain_id,)).fetchone()["n"]
    return {"chain_id": chain_id, "supplier_id": chain["supplier_id"], "created": created,
            "linked_total": int(linked), "new_location_status": "inactive",
            "note": "مکان‌های تازه غیرفعال و بدون قابلیت ارسال ساخته شدند؛ پس از تأیید با زنجیره در پنل فروشنده فعال کنید."}


# ---------------------------------------------------------------- organization coverage

def organization_coverage(conn: sqlite3.Connection, organization_id: int) -> dict:
    """Where this organization's orders ship (and its own city), and how many contracted branches serve each
    place. Built only from the organization's real orders; no guessing of employee locations."""
    org = conn.execute("SELECT id, city FROM organizations WHERE id=?", (organization_id,)).fetchone()
    if org is None:
        raise NotFoundError("سازمان یافت نشد")
    places: dict[tuple[str, str], int] = {}
    for r in conn.execute("SELECT shipping_province, shipping_city, COUNT(*) AS n FROM orders "
                          "WHERE organization_id=? AND status NOT IN ('cancelled','refunded') "
                          "GROUP BY shipping_province, shipping_city", (organization_id,)).fetchall():
        key = (normalize_fa(r["shipping_province"]), normalize_fa(r["shipping_city"]))
        places[key] = places.get(key, 0) + int(r["n"])
    out, unresolved = [], []
    for (prov, city), n in sorted(places.items(), key=lambda kv: -kv[1]):
        try:
            p = resolve_province(conn, prov)
        except ValidationError:
            unresolved.append({"province": prov, "city": city, "orders": n})
            continue
        base = ("SELECT COUNT(*) AS n FROM chain_branches b JOIN retail_chains c ON c.id=b.chain_id "
                "LEFT JOIN network_cities ci ON ci.id=b.city_id WHERE " + _PUBLIC + " AND b.province_id=?")
        in_prov = int(conn.execute(base, (p["id"],)).fetchone()["n"])
        in_city = int(conn.execute(base + " AND ci.name_fa=?", (p["id"], city)).fetchone()["n"])
        out.append({"province": {"slug": p["slug"], "name": p["name_fa"]}, "city": city, "orders": n,
                    "branches_in_city": in_city, "branches_in_province": in_prov,
                    "coverage": "city" if in_city else ("province" if in_prov else "none")})
    return {"organization_id": organization_id, "organization_city": org["city"], "places": out,
            "unresolved_places": unresolved,
            "summary": {k: sum(1 for x in out if x["coverage"] == k) for k in ("city", "province", "none")},
            "basis": "شهرهای مقصد سفارش‌های همین سازمان (به‌جز لغوشده و مرجوع‌شده)"}
