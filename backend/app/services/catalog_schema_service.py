"""Phase 6 — category attribute schemas, typed values, units and variation themes.

* Effective schema of a category = every ancestor's attributes + its own; the nearest row wins per field
  (NULL flag = inherit). An ancestor row with inherit=0 applies to that node only.
* Values are typed: numbers/measures are INTEGER milli-canonical (canonical unit × 1000), so
  «۱٫۵ کیلوگرم» → weight_g = 1 500 000. No floats are stored.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.errors import NotFoundError, ValidationError
from app.services import text_norm as tn

TEXT_MAX = 500   # hard cap for text attribute values, whatever the definition says
RAW_MAX = 2000   # any raw input (lists, measures) beyond this is rejected before parsing
DATA_TYPES = ("text", "number", "integer", "boolean", "enum", "multi_enum", "measure", "date")
FLAGS = ("required", "is_filterable", "is_variant_axis", "is_searchable")
DEFAULT_GROUP = "مشخصات کلی"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬،", "01234567890123456789.,,")
_NUM = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*(.*?)\s*$")
_FA_OUT = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")
TRUE_WORDS = {"1", "true", "yes", "بله", "دارد", "هست", "آری", "بلی"}
FALSE_WORDS = {"0", "false", "no", "خیر", "ندارد", "نیست"}


def latin_digits(s) -> str:
    """Persian/Arabic digits → Latin; «٫» → '.', thousands separators removed."""
    t = str(s).translate(_DIGITS)
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)


def fa_digits(s) -> str:
    return str(s).translate(_FA_OUT)


def _dec(raw) -> Decimal:
    if isinstance(raw, bool):
        raise InvalidOperation
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        return Decimal(repr(raw))
    return Decimal(latin_digits(raw).strip())


def _milli(d: Decimal, factor: int = 1000) -> int:
    return int((d * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fmt_milli(milli: int) -> str:
    d = (Decimal(milli) / 1000).normalize()
    return fa_digits(format(d, "f"))


# ── units ──

def units(conn, kind: str | None = None) -> list[dict]:
    sql, args = "SELECT code, name_fa, kind, factor_to_canonical, is_canonical, aliases FROM units", ()
    if kind:
        sql, args = sql + " WHERE kind=?", (kind,)
    return [dict(r) for r in conn.execute(sql + " ORDER BY kind, factor_to_canonical", args)]


def resolve_unit(conn, kind: str, text: str | None) -> dict | None:
    t = tn.normalize(latin_digits(text or "")).replace("‌", " ").strip().lower()
    t = t.rstrip(".")
    for u in units(conn, kind):
        names = {u["code"].lower(), tn.normalize(u["name_fa"]).replace("‌", " ")}
        names |= {tn.normalize(a).replace("‌", " ").strip().lower() for a in u["aliases"].split(",") if a.strip()}
        if t in names or t.replace(" ", "") in {n.replace(" ", "") for n in names}:
            return u
    return None


def parse_measure(conn, attr: dict, raw) -> tuple[int, str]:
    """→ (milli-canonical integer, unit code as entered). A bare number is taken in the canonical unit."""
    if isinstance(raw, dict):
        value, unit_text = raw.get("value"), raw.get("unit")
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        value, unit_text = raw, None
    else:
        m = _NUM.match(latin_digits(raw or ""))
        if not m:
            raise ValidationError(f"مقدار «{attr['name_fa']}» باید عدد همراه واحد باشد (مثلاً ۵۰۰ گرم)", code="attribute_invalid_measure")
        value, unit_text = m.group(1), m.group(2) or None
    try:
        d = _dec(value)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"مقدار «{attr['name_fa']}» عدد معتبر نیست", code="attribute_invalid_measure")
    if unit_text:
        u = resolve_unit(conn, attr["unit_kind"], unit_text)
        if not u:
            allowed = "، ".join(x["name_fa"] for x in units(conn, attr["unit_kind"]))
            raise ValidationError(f"واحد «{unit_text}» برای «{attr['name_fa']}» معتبر نیست؛ واحدهای مجاز: {allowed}",
                                  code="attribute_invalid_unit")
    else:
        u = next(x for x in units(conn, attr["unit_kind"]) if x["code"] == attr["canonical_unit"])
    return _milli(d, int(u["factor_to_canonical"])), u["code"]


# ── taxonomy helpers ──

def category_by_slug(conn, slug: str) -> dict:
    r = conn.execute("SELECT id, slug, name_fa, parent_id, level FROM categories WHERE slug=?", (slug,)).fetchone()
    if not r:
        raise NotFoundError("دسته یافت نشد", code="category_not_found")
    return dict(r)


def ancestors(conn, category_id: int) -> list[dict]:
    """Root → … → the category itself."""
    out, seen, cid = [], set(), category_id
    while cid is not None and cid not in seen:
        seen.add(cid)
        r = conn.execute("SELECT id, slug, name_fa, parent_id, level FROM categories WHERE id=?", (cid,)).fetchone()
        if not r:
            break
        out.append(dict(r))
        cid = r["parent_id"]
    if not out:
        raise NotFoundError("دسته یافت نشد", code="category_not_found")
    return list(reversed(out))


def options(conn, attribute_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, code, label_fa, sort FROM attribute_options WHERE attribute_id=? AND is_active=1 ORDER BY sort, id", (attribute_id,))]


def definition(conn, code_or_id) -> dict:
    col = "id" if isinstance(code_or_id, int) else "code"
    r = conn.execute(f"SELECT * FROM attribute_definitions WHERE {col}=?", (code_or_id,)).fetchone()
    if not r:
        raise NotFoundError("ویژگی یافت نشد", code="attribute_not_found")
    d = dict(r)
    d["options"] = options(conn, d["id"]) if d["data_type"] in ("enum", "multi_enum") else []
    return d


def effective_schema(conn, category_id: int) -> list[dict]:
    chain = ancestors(conn, category_id)
    merged: dict[int, dict] = {}
    for depth, node in enumerate(chain):
        own = node["id"] == category_id
        for r in conn.execute("""SELECT ca.*, a.code, a.status FROM category_attributes ca JOIN attribute_definitions a ON a.id=ca.attribute_id
                                 WHERE ca.category_id=? ORDER BY ca.id""", (node["id"],)):
            if r["status"] != "active" or (not own and not r["inherit"]):
                continue
            e = merged.setdefault(r["attribute_id"], {"attribute_id": r["attribute_id"], "code": r["code"], "defined_at": node["slug"],
                                                      **{f: None for f in FLAGS}, "display_group_fa": None, "sort": None})
            for f in (*FLAGS, "display_group_fa", "sort"):
                if r[f] is not None:
                    e[f] = r[f]
            e["overridden_at"] = node["slug"] if e["defined_at"] != node["slug"] else None
    out = []
    for aid, e in merged.items():
        d = definition(conn, aid)
        out.append({"code": d["code"], "name_fa": d["name_fa"], "data_type": d["data_type"], "unit_kind": d["unit_kind"],
                    "canonical_unit": d["canonical_unit"], "units": [{"code": u["code"], "name_fa": u["name_fa"]} for u in units(conn, d["unit_kind"])] if d["unit_kind"] else [],
                    "min_value": d["min_value"], "max_value": d["max_value"], "regex": d["regex"], "help_fa": d["help_fa"],
                    "options": [{"code": o["code"], "label_fa": o["label_fa"]} for o in d["options"]],
                    **{f: bool(e[f]) for f in FLAGS}, "display_group_fa": e["display_group_fa"] or DEFAULT_GROUP,
                    "sort": e["sort"] if e["sort"] is not None else 1000, "attribute_id": aid,
                    "defined_at": e["defined_at"], "overridden_at": e.get("overridden_at")})
    out.sort(key=lambda a: (a["sort"], a["code"]))
    return out


def variation_theme(conn, category_id: int, code: str | None = None) -> dict | None:
    """Nearest theme up the tree (a named code, else the default)."""
    for node in reversed(ancestors(conn, category_id)):
        sql = "SELECT * FROM category_variation_themes WHERE category_id=? AND " + ("code=?" if code else "is_default=1")
        r = conn.execute(sql + " ORDER BY id LIMIT 1", (node["id"], code) if code else (node["id"],)).fetchone()
        if r:
            return {"code": r["code"], "name_fa": r["name_fa"], "axes": [a.strip() for a in r["axes"].split(",") if a.strip()],
                    "defined_at": node["slug"]}
    return None


def themes(conn, category_id: int) -> list[dict]:
    seen, out = set(), []
    for node in reversed(ancestors(conn, category_id)):
        for r in conn.execute("SELECT * FROM category_variation_themes WHERE category_id=? ORDER BY id", (node["id"],)):
            if r["code"] not in seen:
                seen.add(r["code"])
                out.append({"id": r["id"], "code": r["code"], "name_fa": r["name_fa"], "axes": r["axes"].split(","),
                            "is_default": bool(r["is_default"]), "defined_at": node["slug"]})
    return out


# ── value coercion ──

def coerce(conn, attr: dict, raw) -> list[dict]:
    """Validate one raw value against its definition → value rows (several for multi_enum). Raises ValidationError (Persian)."""
    name, dt = attr["name_fa"], attr["data_type"]
    if len(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)) > RAW_MAX:
        raise ValidationError(f"«{name}» بیش از حد طولانی است", code="attribute_too_long")
    base = {"value_key": "", "value_text": None, "value_number": None, "value_bool": None, "option_id": None, "unit_entered": None,
            "raw_value": raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)}
    lo, hi = attr.get("min_value"), attr.get("max_value")
    if dt == "text":
        v = str(raw).strip()
        if not v:
            raise ValidationError(f"«{name}» خالی است", code="attribute_empty")
        cap = min(int(hi), TEXT_MAX) if hi is not None else TEXT_MAX
        if len(v) > cap:
            hi = cap
            raise ValidationError(f"«{name}» حداکثر {fa_digits(hi)} نویسه است", code="attribute_too_long")
        if attr.get("regex") and not re.fullmatch(attr["regex"], v):
            raise ValidationError(f"قالب «{name}» معتبر نیست", code="attribute_bad_format")
        return [{**base, "value_text": v}]
    if dt in ("number", "integer", "measure"):
        if dt == "measure":
            milli, unit = parse_measure(conn, attr, raw)
            base["unit_entered"] = unit
        else:
            try:
                d = _dec(raw)
            except (InvalidOperation, ValueError):
                raise ValidationError(f"«{name}» باید عدد باشد", code="attribute_not_number")
            if dt == "integer" and d != d.to_integral_value():
                raise ValidationError(f"«{name}» باید عدد صحیح باشد", code="attribute_not_integer")
            milli = _milli(d)
        if milli < 0:
            raise ValidationError(f"«{name}» نمی‌تواند منفی باشد", code="attribute_out_of_range")
        if lo is not None and milli < lo * 1000 or hi is not None and milli > hi * 1000:
            unit = f" {attr.get('canonical_unit')}" if dt == "measure" else ""
            raise ValidationError(f"«{name}» باید بین {fa_digits(lo if lo is not None else 0)} و {fa_digits(hi) if hi is not None else '∞'}{unit} باشد",
                                  code="attribute_out_of_range")
        return [{**base, "value_number": milli}]
    if dt == "boolean":
        if isinstance(raw, bool):
            return [{**base, "value_bool": int(raw)}]
        t = tn.normalize(latin_digits(raw)).strip().lower()
        if t in TRUE_WORDS or t in FALSE_WORDS:
            return [{**base, "value_bool": int(t in TRUE_WORDS)}]
        raise ValidationError(f"«{name}» باید بله یا خیر باشد", code="attribute_not_boolean")
    if dt in ("enum", "multi_enum"):
        items = raw if isinstance(raw, list) else re.split(r"[,،]", str(raw)) if dt == "multi_enum" else [raw]
        opts = attr.get("options") or options(conn, attr["attribute_id"] if "attribute_id" in attr else attr["id"])
        rows = []
        for item in items:
            t = tn.normalize(str(item)).strip()
            if not t:
                continue
            o = next((o for o in opts if o["code"] == str(item).strip() or tn.normalize(o["label_fa"]) == t or o["code"] == t), None)
            if not o:
                allowed = "، ".join(x["label_fa"] for x in opts)
                raise ValidationError(f"«{item}» برای «{name}» مجاز نیست؛ گزینه‌های مجاز: {allowed}", code="attribute_invalid_option")
            oid = o.get("id") or conn.execute("SELECT o.id FROM attribute_options o JOIN attribute_definitions a ON a.id=o.attribute_id WHERE a.code=? AND o.code=?",
                                              (attr["code"], o["code"])).fetchone()[0]
            if any(r["option_id"] == oid for r in rows):
                continue
            rows.append({**base, "option_id": oid, "value_text": o["code"], "value_key": o["code"] if dt == "multi_enum" else ""})
        if not rows:
            raise ValidationError(f"«{name}» خالی است", code="attribute_empty")
        if dt == "enum" and len(rows) > 1:
            raise ValidationError(f"«{name}» فقط یک گزینه می‌پذیرد", code="attribute_single_option")
        return rows
    if dt == "date":
        try:
            v = _dt.date.fromisoformat(latin_digits(raw).strip()).isoformat()
        except ValueError:
            raise ValidationError(f"تاریخ «{name}» باید به شکل YYYY-MM-DD باشد", code="attribute_bad_date")
        return [{**base, "value_text": v}]
    raise ValidationError("نوع ویژگی ناشناخته است")


def validate_attributes(conn, category_id: int, values: dict) -> dict:
    """→ {"errors": [{code, attribute, message}], "rows": {code: [rows]}, "schema": [...]} — never raises for bad values."""
    if not isinstance(values, dict):
        raise ValidationError("ویژگی‌ها باید به شکل شیء کلید/مقدار باشند")
    schema = effective_schema(conn, category_id)
    by_code = {a["code"]: a for a in schema}
    errors, rows = [], {}
    for code, raw in values.items():
        if raw is None or raw == "" or raw == []:
            continue
        a = by_code.get(code)
        if not a:
            errors.append({"code": "attribute_not_in_category", "attribute": code, "message": f"ویژگی «{code}» برای این دسته تعریف نشده است"})
            continue
        try:
            rows[code] = coerce(conn, a, raw)
        except ValidationError as e:
            errors.append({"code": e.code or "attribute_invalid", "attribute": code, "message": str(e)})
    return {"errors": errors, "rows": rows, "schema": schema}


# ── persistence ──

def category_of_master(conn, master_product_id: int) -> int | None:
    r = conn.execute("""SELECT COALESCE(f.category_id,
                                (SELECT p.category_id FROM products p WHERE p.master_product_id=m.id ORDER BY p.id LIMIT 1),
                                (SELECT c.id FROM categories c WHERE c.slug=m.category)) AS cid
                        FROM master_products m LEFT JOIN product_families f ON f.id=m.family_id WHERE m.id=?""", (master_product_id,)).fetchone()
    if r is None:
        raise NotFoundError("محصول یافت نشد", code="product_not_found")
    return r["cid"]


def set_values(conn, master_product_id: int, values: dict, *, source: str = "admin", category_id: int | None = None,
               seller_id: int | None = None, seller_full: bool = False) -> dict:
    """Validate then write (replacing the given attributes only). Raises ValidationError with all errors in details.

    Seller writes (seller_id given): a master is shared catalog data. A seller with full rights (recorded source or the
    only active seller) may replace attributes that only hold seller rows; otherwise — or where admin/backfill/import
    rows exist — a differing value becomes a proposal for review, and non-seller rows are never deleted.
    """
    cid = category_id or category_of_master(conn, master_product_id)
    if cid is None:
        raise ValidationError("دستهٔ محصول مشخص نیست", code="category_required")
    res = validate_attributes(conn, cid, values)
    if res["errors"]:
        raise ValidationError(res["errors"][0]["message"], code="attribute_validation_failed", details={"errors": res["errors"]})
    by_code = {a["code"]: a for a in res["schema"]}
    proposed, skipped = [], []

    def sources(aid):
        return {r[0] for r in conn.execute("SELECT DISTINCT source FROM product_attribute_values WHERE master_product_id=? AND attribute_id=?",
                                           (master_product_id, aid))}

    def can_replace(aid):
        if seller_id is None:
            return True
        have = sources(aid)
        return not have or (seller_full and have <= {"seller"})

    for code, raw in values.items():
        if code in by_code and (raw is None or raw == "" or raw == []):
            aid = by_code[code]["attribute_id"]
            if seller_id is not None and not (seller_full and sources(aid) <= {"seller"}):
                skipped.append(code)
                continue
            conn.execute("DELETE FROM product_attribute_values WHERE master_product_id=? AND attribute_id=?", (master_product_id, aid))
    written = []
    for code, rws in res["rows"].items():
        aid = by_code[code]["attribute_id"]
        if not can_replace(aid):
            sig = ("value_key", "value_text", "value_number", "value_bool", "option_id")
            current = sorted(tuple(str(r[k]) for k in sig) for r in conn.execute(
                "SELECT * FROM product_attribute_values WHERE master_product_id=? AND attribute_id=?", (master_product_id, aid)))
            if current != sorted(tuple(str(r[k]) for k in sig) for r in rws):
                raw = values[code]
                conn.execute("INSERT INTO product_attribute_proposals (master_product_id, attribute_id, supplier_id, raw_value) VALUES (?,?,?,?)",
                             (master_product_id, aid, seller_id, raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)))
                proposed.append(code)
            continue
        conn.execute("DELETE FROM product_attribute_values WHERE master_product_id=? AND attribute_id=?", (master_product_id, aid))
        for r in rws:
            conn.execute("""INSERT INTO product_attribute_values (master_product_id, attribute_id, value_key, value_text, value_number, value_bool,
                                option_id, unit_entered, raw_value, source) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (master_product_id, aid, r["value_key"], r["value_text"], r["value_number"], r["value_bool"], r["option_id"],
                          r["unit_entered"], r["raw_value"], source))
        written.append(code)
    out = {"master_product_id": master_product_id, "written": sorted(written), "values": get_values(conn, master_product_id)}
    if seller_id is not None:
        out["proposed"] = sorted(proposed)
        out["skipped"] = sorted(skipped)
    return out


def _value_rows(conn, master_product_id: int):
    return conn.execute("""SELECT v.*, a.code, a.name_fa, a.data_type, a.unit_kind, a.canonical_unit, o.label_fa AS option_label
                           FROM product_attribute_values v JOIN attribute_definitions a ON a.id=v.attribute_id
                           LEFT JOIN attribute_options o ON o.id=v.option_id WHERE v.master_product_id=? ORDER BY v.attribute_id, v.id""",
                        (master_product_id,)).fetchall()


def _display_measure(conn, kind: str, milli: int) -> str:
    us = [u for u in units(conn, kind) if u["kind"] == kind]
    best = None
    for u in sorted(us, key=lambda u: u["factor_to_canonical"]):
        if milli >= u["factor_to_canonical"] and u["code"] not in ("mg",):
            best = u
    best = best or next((u for u in us if u["is_canonical"]), us[0])
    return f"{fmt_milli(milli * 1000 // best['factor_to_canonical'])} {best['name_fa']}"


def display(conn, r) -> str:
    dt = r["data_type"]
    if dt == "measure":
        return _display_measure(conn, r["unit_kind"], r["value_number"])
    if dt in ("number", "integer"):
        return fmt_milli(r["value_number"])
    if dt == "boolean":
        return "بله" if r["value_bool"] else "خیر"
    if dt in ("enum", "multi_enum"):
        return r["option_label"] or r["value_text"]
    return r["value_text"]


def get_values(conn, master_product_id: int) -> dict:
    """{code: python value}: measures/numbers → milli int ÷ 1000 as int when whole (canonical unit), enums → code(s)."""
    out: dict = {}
    for r in _value_rows(conn, master_product_id):
        dt = r["data_type"]
        if dt in ("number", "integer", "measure"):
            v = r["value_number"] // 1000 if r["value_number"] % 1000 == 0 else str(Decimal(r["value_number"]) / 1000)
        elif dt == "boolean":
            v = bool(r["value_bool"])
        else:
            v = r["value_text"]
        if dt == "multi_enum":
            out.setdefault(r["code"], []).append(v)
        else:
            out[r["code"]] = v
    return out


def raw_milli(conn, master_product_id: int) -> dict:
    return {r["code"]: r["value_number"] for r in _value_rows(conn, master_product_id) if r["value_number"] is not None}


def spec_groups(conn, master_product_id: int, category_id: int | None) -> list[dict]:
    """Specs table grouped by display_group (schema order); values outside the schema go to «سایر مشخصات»."""
    schema = {a["code"]: a for a in effective_schema(conn, category_id)} if category_id else {}
    items: dict[str, dict] = {}
    for r in _value_rows(conn, master_product_id):
        e = items.setdefault(r["code"], {"code": r["code"], "label_fa": r["name_fa"], "values": []})
        e["values"].append(display(conn, r))
    groups: dict[str, list] = {}
    order = sorted(items.values(), key=lambda i: (schema[i["code"]]["sort"] if i["code"] in schema else 10_000, i["code"]))
    for i in order:
        g = schema[i["code"]]["display_group_fa"] if i["code"] in schema else "سایر مشخصات"
        groups.setdefault(g, []).append({"code": i["code"], "label_fa": i["label_fa"], "value_fa": "، ".join(i["values"])})
    return [{"group_fa": g, "items": v} for g, v in groups.items()]


# ── variation themes ──

def check_family(conn, family_id: int) -> dict:
    """Siblings must each carry every theme axis, differ in the axis combination, and agree on non-axis schema values."""
    f = conn.execute("SELECT id, category_id, variation_theme_code FROM product_families WHERE id=?", (family_id,)).fetchone()
    if not f:
        raise NotFoundError("خانوادهٔ محصول یافت نشد")
    if f["category_id"] is None:
        return {"family_id": family_id, "ok": False, "theme": None, "errors": [{"code": "category_required", "message": "دستهٔ خانواده مشخص نیست"}]}
    theme = variation_theme(conn, f["category_id"], f["variation_theme_code"])
    members = [r["id"] for r in conn.execute("SELECT id FROM master_products WHERE family_id=? AND status='active' ORDER BY id", (family_id,))]
    errors: list[dict] = []
    if not theme:
        return {"family_id": family_id, "ok": len(members) <= 1, "theme": None, "members": members,
                "errors": [] if len(members) <= 1 else [{"code": "theme_missing", "message": "برای این دسته الگوی تنوع تعریف نشده است"}]}
    axes = theme["axes"]
    schema_codes = {a["code"] for a in effective_schema(conn, f["category_id"])}
    vals = {m: get_values(conn, m) for m in members}
    seen: dict[tuple, int] = {}
    for m in members:
        missing = [a for a in axes if a not in vals[m]]
        if missing:
            errors.append({"code": "variant_axis_missing", "master_product_id": m, "attributes": missing,
                           "message": f"تنوع {fa_digits(m)}: مقدار محور(های) {'، '.join(missing)} وارد نشده است"})
            continue
        combo = tuple(json.dumps(vals[m][a], sort_keys=True) for a in axes)
        if combo in seen:
            errors.append({"code": "variant_duplicate", "master_product_id": m, "duplicate_of": seen[combo],
                           "message": f"تنوع {fa_digits(m)} با تنوع {fa_digits(seen[combo])} در محورهای تنوع یکسان است"})
        else:
            seen[combo] = m
    for code in sorted(schema_codes - set(axes)):
        present = {json.dumps(vals[m][code], sort_keys=True) for m in members if code in vals[m]}
        if len(present) > 1:
            errors.append({"code": "variant_non_axis_differs", "attribute": code,
                           "message": f"ویژگی «{code}» بین تنوع‌ها متفاوت است ولی جزو محورهای تنوع نیست"})
    return {"family_id": family_id, "ok": not errors, "theme": theme, "members": members, "errors": errors}


# ── backfill ──

_BACKFILL_JSON = {"weight_g": "weight_g", "volume_ml": "volume_ml"}


def backfill(conn, *, dry_run: bool = False) -> dict:
    """Typed values from attributes_json / size_label / net_quantity / package_quantity / country_of_origin.
    Only unambiguous values; never overwrites an existing value."""
    defs = {c: dict(r) for c in ("weight_g", "volume_ml", "pack_count", "origin", "paper_size")
            for r in [conn.execute("SELECT * FROM attribute_definitions WHERE code=?", (c,)).fetchone()] if r}
    counts = {"scanned": 0, "inserted": 0, "skipped_existing": 0, "ambiguous": 0, "products_touched": 0}
    for m in conn.execute("SELECT id, attributes_json, size_label, net_quantity, package_quantity, country_of_origin FROM master_products").fetchall():
        counts["scanned"] += 1
        cand: dict[str, set] = {}
        try:
            aj = json.loads(m["attributes_json"] or "{}")
        except ValueError:
            aj = {}
        for k, code in _BACKFILL_JSON.items():
            if isinstance(aj, dict) and isinstance(aj.get(k), (int, float)) and not isinstance(aj.get(k), bool) and aj[k] > 0:
                cand.setdefault(code, set()).add(_milli(_dec(aj[k])))
        for src in (m["size_label"], m["net_quantity"]):
            for k, v in tn.measures(src).items():
                if k in _BACKFILL_JSON:
                    cand.setdefault(_BACKFILL_JSON[k], set()).add(_milli(_dec(v)))
            t = (src or "").strip().upper()
            if t in ("A3", "A4", "A5", "B5"):
                cand.setdefault("paper_size", set()).add(t.lower())
        if (m["package_quantity"] or 1) > 1:
            cand.setdefault("pack_count", set()).add(int(m["package_quantity"]) * 1000)
        if m["country_of_origin"] and m["country_of_origin"].strip():
            cand.setdefault("origin", set()).add(m["country_of_origin"].strip())
        touched = False
        for code, vs in cand.items():
            d = defs.get(code)
            if not d:
                continue
            if len(vs) != 1:
                counts["ambiguous"] += 1
                continue
            if conn.execute("SELECT 1 FROM product_attribute_values WHERE master_product_id=? AND attribute_id=?", (m["id"], d["id"])).fetchone():
                counts["skipped_existing"] += 1
                continue
            v = next(iter(vs))
            row = {"value_text": None, "value_number": None, "option_id": None, "unit": None}
            if code == "paper_size":
                o = conn.execute("SELECT id FROM attribute_options WHERE attribute_id=? AND code=?", (d["id"], v)).fetchone()
                if not o:
                    continue
                row.update(value_text=v, option_id=o["id"])
            elif code == "origin":
                row["value_text"] = v[:60]
            else:
                row.update(value_number=v, unit=d["canonical_unit"] or "pcs")
            counts["inserted"] += 1
            touched = True
            if not dry_run:
                conn.execute("""INSERT INTO product_attribute_values (master_product_id, attribute_id, value_text, value_number, option_id, unit_entered, source)
                                VALUES (?,?,?,?,?,?,'backfill')""", (m["id"], d["id"], row["value_text"], row["value_number"], row["option_id"], row["unit"]))
        counts["products_touched"] += int(touched)
    counts["dry_run"] = dry_run
    return counts
