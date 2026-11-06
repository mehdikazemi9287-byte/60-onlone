"""Phase 6 — catalog attribute schemas, listing policies, quality checks and feed mappings.

Blueprint `catalog_schema` (url_prefix /api/v1):
  Public   GET  /categories/<slug>/schema                 effective schema + theme + policy + SEO (seller forms, filters)
           GET  /catalog/units
  Seller   POST /supplier/catalog/validate                attributes → errors, score, checklist, suggested title
  Admin    /admin/catalog/attributes[/<id>], /attributes/<id>/options, /options/<id>,
           /admin/catalog/categories/<id>/attributes[/<code>], /policy, /themes[/<code>], /mappings,
           /admin/catalog/products/<mid>/attributes, /products/<mid>/quality, /quality, /families/<fid>/variation-check,
           /admin/catalog/attributes/backfill, /admin/catalog/policies/apply-defaults
"""
import json
import re

from flask import Blueprint, jsonify, request

from app.core.deps import current_user, get_db, require_auth
from app.core.errors import ConflictError, NotFoundError, PermissionError_, ValidationError
from app.services import catalog_quality_service as cq
from app.services import catalog_schema_service as cs
from app.services.access_admin_service import current_supplier_id

bp = Blueprint("catalog_schema", __name__, url_prefix="/api/v1")
_CODE = re.compile(r"^[a-z][a-z0-9_]{1,59}$")
_SOURCES = ("torob", "basalam", "digikala", "emalls", "google", "gs1_gpc")


def _body() -> dict:
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        raise ValidationError("بدنه درخواست باید شیء باشد")
    return d


def _str(d, key, maximum=200, required=False):
    v = d.get(key)
    if v is None or v == "":
        if required:
            raise ValidationError(f"«{key}» الزامی است")
        return None
    if not isinstance(v, str) or len(v) > maximum:
        raise ValidationError(f"«{key}» نامعتبر است")
    return v.strip()


def _int(d, key, lo=None, hi=None):
    v = d.get(key)
    if v is None:
        return None
    if type(v) is not int or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValidationError(f"«{key}» باید عدد صحیح معتبر باشد")
    return v


def _flag(d, key):
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, bool) and v not in (0, 1):
        raise ValidationError(f"«{key}» باید صفر/یک باشد")
    return int(v)


def _category(conn, cid: int) -> dict:
    return cs.ancestors(conn, cid)[-1]


# ── public ──

@bp.get("/categories/<slug>/schema")
def category_schema(slug: str):
    with get_db().read_transaction() as conn:
        c = cs.category_by_slug(conn, slug)
        policy = cq.effective_policy(conn, c["id"])
        policy.pop("sources", None)
        return jsonify({"category": c, "attributes": cs.effective_schema(conn, c["id"]), "variation_theme": cs.variation_theme(conn, c["id"]),
                        "variation_themes": cs.themes(conn, c["id"]), "policy": policy, "seo": cq.category_seo(conn, c["id"])})


@bp.get("/catalog/units")
def list_units():
    with get_db().read_transaction() as conn:
        return jsonify({"items": cs.units(conn)})


# ── seller ──

@bp.post("/supplier/catalog/validate")
@require_auth()
def supplier_validate():
    d = _body()
    with get_db().read_transaction() as conn:
        if current_user().get("role") != "admin" and not current_supplier_id(conn, current_user()["id"]):
            raise PermissionError_("حساب تأمین‌کننده برای این کاربر یافت نشد")
        if d.get("category_slug"):
            cid = cs.category_by_slug(conn, str(d["category_slug"]))["id"]
        else:
            cid = _int(d, "category_id", 1)
            if cid is None:
                raise ValidationError("دستهٔ کالا (category_id یا category_slug) الزامی است", code="category_required")
        images = d.get("images") or []
        if not isinstance(images, list):
            raise ValidationError("تصاویر باید فهرست باشد")
        attrs = d.get("attributes") or {}
        out = cq.evaluate(conn, category_id=cid, title=_str(d, "title", 500), brand=_str(d, "brand", 120), model=_str(d, "model", 120),
                          images=images, description=_str(d, "description", 20000), attributes=attrs)
        out["valid"] = not out["errors"] and not out["missing_required"]
        out["enforced"] = cq.enforce_required()
        return jsonify(out)


# ── admin: definitions & options ──

def _def_values(d, partial=False):
    out = {}
    if not partial or "code" in d:
        code = _str(d, "code", 60, required=True)
        if not _CODE.match(code):
            raise ValidationError("کد ویژگی باید لاتین کوچک، عدد و _ باشد")
        out["code"] = code
    if not partial or "name_fa" in d:
        out["name_fa"] = _str(d, "name_fa", 120, required=True)
    if not partial or "data_type" in d:
        dt = d.get("data_type")
        if dt not in cs.DATA_TYPES:
            raise ValidationError("نوع دادهٔ ویژگی نامعتبر است")
        out["data_type"] = dt
    for k in ("unit_kind", "canonical_unit", "regex", "help_fa"):
        if k in d:
            out[k] = _str(d, k, 500)
    for k in ("min_value", "max_value"):
        if k in d:
            out[k] = _int(d, k)
    if "status" in d:
        if d["status"] not in ("active", "archived"):
            raise ValidationError("وضعیت نامعتبر است")
        out["status"] = d["status"]
    if out.get("regex"):
        try:
            re.compile(out["regex"])
        except re.error:
            raise ValidationError("عبارت باقاعده نامعتبر است")
    return out


def _check_def(conn, row: dict):
    if row["data_type"] == "measure":
        if not row.get("unit_kind") or not row.get("canonical_unit"):
            raise ValidationError("ویژگی اندازه‌ای به نوع واحد و واحد پایه نیاز دارد")
        u = conn.execute("SELECT kind FROM units WHERE code=?", (row["canonical_unit"],)).fetchone()
        if not u or u["kind"] != row["unit_kind"]:
            raise ValidationError("واحد پایه با نوع واحد سازگار نیست")


@bp.get("/admin/catalog/attributes")
@require_auth("admin")
def attributes_list():
    with get_db().read_transaction() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM attribute_definitions ORDER BY code")]
        for r in rows:
            r["options"] = cs.options(conn, r["id"]) if r["data_type"] in ("enum", "multi_enum") else []
        return jsonify({"items": rows})


@bp.post("/admin/catalog/attributes")
@require_auth("admin")
def attributes_create():
    d = _body()
    v = _def_values(d)
    with get_db().write_transaction() as conn:
        _check_def(conn, v)
        if conn.execute("SELECT 1 FROM attribute_definitions WHERE code=?", (v["code"],)).fetchone():
            raise ConflictError("کد ویژگی تکراری است", code="attribute_exists")
        cols = ", ".join(v)
        aid = conn.execute(f"INSERT INTO attribute_definitions ({cols}) VALUES ({','.join('?' * len(v))})", tuple(v.values())).lastrowid
        for i, o in enumerate(d.get("options") or []):
            _option_insert(conn, aid, o, i + 1)
        return jsonify({"attribute": cs.definition(conn, aid)}), 201


@bp.put("/admin/catalog/attributes/<int:aid>")
@require_auth("admin")
def attributes_update(aid: int):
    v = _def_values(_body(), partial=True)
    v.pop("code", None)
    with get_db().write_transaction() as conn:
        cur = cs.definition(conn, aid)
        if "data_type" in v and v["data_type"] != cur["data_type"] and conn.execute(
                "SELECT 1 FROM product_attribute_values WHERE attribute_id=? LIMIT 1", (aid,)).fetchone():
            raise ConflictError("نوع دادهٔ ویژگی دارای مقدار ثبت‌شده قابل تغییر نیست", code="attribute_in_use")
        _check_def(conn, {**cur, **v})
        if v:
            conn.execute(f"UPDATE attribute_definitions SET {', '.join(k + '=?' for k in v)}, updated_at=? WHERE id=?",
                         (*v.values(), cq_now(), aid))
        return jsonify({"attribute": cs.definition(conn, aid)})


@bp.delete("/admin/catalog/attributes/<int:aid>")
@require_auth("admin")
def attributes_archive(aid: int):
    with get_db().write_transaction() as conn:
        cs.definition(conn, aid)
        conn.execute("UPDATE attribute_definitions SET status='archived', updated_at=? WHERE id=?", (cq_now(), aid))
        return jsonify({"attribute": cs.definition(conn, aid)})


def cq_now():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _option_insert(conn, aid, o, sort):
    if not isinstance(o, dict):
        raise ValidationError("گزینه باید شیء باشد")
    code, label = _str(o, "code", 60, required=True), _str(o, "label_fa", 120, required=True)
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,59}$", code):
        raise ValidationError("کد گزینه باید لاتین کوچک باشد")
    if conn.execute("SELECT 1 FROM attribute_options WHERE attribute_id=? AND code=?", (aid, code)).fetchone():
        raise ConflictError("کد گزینه تکراری است", code="option_exists")
    return conn.execute("INSERT INTO attribute_options (attribute_id, code, label_fa, sort) VALUES (?,?,?,?)",
                        (aid, code, label, _int(o, "sort", 0, 100000) or sort)).lastrowid


@bp.post("/admin/catalog/attributes/<int:aid>/options")
@require_auth("admin")
def options_create(aid: int):
    d = _body()
    with get_db().write_transaction() as conn:
        a = cs.definition(conn, aid)
        if a["data_type"] not in ("enum", "multi_enum"):
            raise ValidationError("فقط ویژگی‌های گزینه‌ای گزینه دارند")
        oid = _option_insert(conn, aid, d, len(a["options"]) + 1)
        return jsonify({"option": dict(conn.execute("SELECT * FROM attribute_options WHERE id=?", (oid,)).fetchone())}), 201


@bp.put("/admin/catalog/options/<int:oid>")
@require_auth("admin")
def options_update(oid: int):
    d = _body()
    with get_db().write_transaction() as conn:
        if not conn.execute("SELECT 1 FROM attribute_options WHERE id=?", (oid,)).fetchone():
            raise NotFoundError("گزینه یافت نشد")
        label, sort, active = _str(d, "label_fa", 120), _int(d, "sort", 0, 100000), _flag(d, "is_active")
        conn.execute("UPDATE attribute_options SET label_fa=COALESCE(?, label_fa), sort=COALESCE(?, sort), is_active=COALESCE(?, is_active) WHERE id=?",
                     (label, sort, active, oid))
        return jsonify({"option": dict(conn.execute("SELECT * FROM attribute_options WHERE id=?", (oid,)).fetchone())})


@bp.delete("/admin/catalog/options/<int:oid>")
@require_auth("admin")
def options_delete(oid: int):
    with get_db().write_transaction() as conn:
        if conn.execute("SELECT 1 FROM product_attribute_values WHERE option_id=? LIMIT 1", (oid,)).fetchone():
            conn.execute("UPDATE attribute_options SET is_active=0 WHERE id=?", (oid,))
            return jsonify({"deleted": False, "deactivated": True})
        conn.execute("DELETE FROM attribute_options WHERE id=?", (oid,))
        return jsonify({"deleted": True})


# ── admin: category bindings, policy, themes, mappings ──

@bp.get("/admin/catalog/categories/<int:cid>/attributes")
@require_auth("admin")
def category_attributes(cid: int):
    with get_db().read_transaction() as conn:
        _category(conn, cid)
        own = [dict(r) for r in conn.execute("""SELECT ca.*, a.code FROM category_attributes ca JOIN attribute_definitions a ON a.id=ca.attribute_id
                                                 WHERE ca.category_id=? ORDER BY ca.sort, ca.id""", (cid,))]
        return jsonify({"own": own, "effective": cs.effective_schema(conn, cid)})


@bp.put("/admin/catalog/categories/<int:cid>/attributes/<code>")
@require_auth("admin")
def category_attribute_upsert(cid: int, code: str):
    d = _body()
    with get_db().write_transaction() as conn:
        _category(conn, cid)
        a = cs.definition(conn, code)
        vals = {k: _flag(d, k) for k in cs.FLAGS}
        group, sort = _str(d, "display_group_fa", 80), _int(d, "sort", 0, 100000)
        inherit = _flag(d, "inherit")
        if conn.execute("SELECT 1 FROM category_attributes WHERE category_id=? AND attribute_id=?", (cid, a["id"])).fetchone():
            conn.execute("""UPDATE category_attributes SET required=?, is_filterable=?, is_variant_axis=?, is_searchable=?, display_group_fa=?, sort=?,
                            inherit=? WHERE category_id=? AND attribute_id=?""",
                         (*vals.values(), group, sort, 1 if inherit is None else inherit, cid, a["id"]))
        else:
            conn.execute("""INSERT INTO category_attributes (category_id, attribute_id, required, is_filterable, is_variant_axis, is_searchable,
                            display_group_fa, sort, inherit) VALUES (?,?,?,?,?,?,?,?,?)""",
                         (cid, a["id"], *vals.values(), group, sort, 1 if inherit is None else inherit))
        return jsonify({"effective": cs.effective_schema(conn, cid)})


@bp.delete("/admin/catalog/categories/<int:cid>/attributes/<code>")
@require_auth("admin")
def category_attribute_delete(cid: int, code: str):
    with get_db().write_transaction() as conn:
        a = cs.definition(conn, code)
        conn.execute("DELETE FROM category_attributes WHERE category_id=? AND attribute_id=?", (cid, a["id"]))
        return jsonify({"effective": cs.effective_schema(conn, cid)})


@bp.get("/admin/catalog/categories/<int:cid>/policy")
@require_auth("admin")
def policy_get(cid: int):
    with get_db().read_transaction() as conn:
        _category(conn, cid)
        own = conn.execute("SELECT * FROM category_listing_policies WHERE category_id=?", (cid,)).fetchone()
        return jsonify({"own": dict(own) if own else None, "effective": cq.effective_policy(conn, cid)})


@bp.put("/admin/catalog/categories/<int:cid>/policy")
@require_auth("admin")
def policy_put(cid: int):
    d = _body()
    v: dict = {}
    for k in ("title_template", "banned_words", "tax_category", "meta_title_template", "meta_description_template", "required_attribute_codes"):
        if k in d:
            v[k] = _str(d, k, 2000)
    if "withdrawal_exempt_default" in d:
        if d["withdrawal_exempt_default"] not in (None, "none", "perishable", "custom_made", "hygiene", "digital"):
            raise ValidationError("دلیل استثنای انصراف نامعتبر است")
        v["withdrawal_exempt_default"] = d["withdrawal_exempt_default"]
    for k, lo, hi in (("min_images", 0, 20), ("max_title_length", 10, 500), ("return_window_days", 0, 90), ("commission_hint_bps", 0, 10000)):
        if k in d:
            v[k] = _int(d, k, lo, hi)
    for k in ("requires_cold_chain", "is_perishable", "is_fragile", "is_hazardous"):
        if k in d:
            v[k] = _flag(d, k)
    if not v:
        raise ValidationError("هیچ فیلدی برای ذخیره ارسال نشده است")
    with get_db().write_transaction() as conn:
        _category(conn, cid)
        for code in (v.get("required_attribute_codes") or "").split(","):
            if code.strip():
                cs.definition(conn, code.strip())
        if not conn.execute("SELECT 1 FROM category_listing_policies WHERE category_id=?", (cid,)).fetchone():
            conn.execute("INSERT INTO category_listing_policies (category_id) VALUES (?)", (cid,))
        conn.execute(f"UPDATE category_listing_policies SET {', '.join(k + '=?' for k in v)}, updated_at=? WHERE category_id=?",
                     (*v.values(), cq_now(), cid))
        return jsonify({"effective": cq.effective_policy(conn, cid)})


@bp.get("/admin/catalog/categories/<int:cid>/themes")
@require_auth("admin")
def themes_get(cid: int):
    with get_db().read_transaction() as conn:
        return jsonify({"items": cs.themes(conn, cid), "default": cs.variation_theme(conn, cid)})


@bp.put("/admin/catalog/categories/<int:cid>/themes/<code>")
@require_auth("admin")
def themes_put(cid: int, code: str):
    d = _body()
    axes = d.get("axes")
    if not isinstance(axes, list) or not axes or not all(isinstance(a, str) for a in axes):
        raise ValidationError("محورهای تنوع باید فهرستی از کد ویژگی‌ها باشد")
    name = _str(d, "name_fa", 120, required=True)
    default = _flag(d, "is_default")
    with get_db().write_transaction() as conn:
        _category(conn, cid)
        schema = {a["code"] for a in cs.effective_schema(conn, cid)}
        bad = [a for a in axes if a not in schema]
        if bad:
            raise ValidationError(f"محور «{bad[0]}» در ویژگی‌های این دسته نیست", code="theme_axis_not_in_schema")
        if default in (None, 1):
            conn.execute("UPDATE category_variation_themes SET is_default=0 WHERE category_id=?", (cid,))
        conn.execute("DELETE FROM category_variation_themes WHERE category_id=? AND code=?", (cid, code))
        conn.execute("INSERT INTO category_variation_themes (category_id, code, name_fa, axes, is_default) VALUES (?,?,?,?,?)",
                     (cid, code, name, ",".join(axes), 1 if default is None else default))
        return jsonify({"items": cs.themes(conn, cid), "default": cs.variation_theme(conn, cid)})


@bp.delete("/admin/catalog/categories/<int:cid>/themes/<code>")
@require_auth("admin")
def themes_delete(cid: int, code: str):
    with get_db().write_transaction() as conn:
        conn.execute("DELETE FROM category_variation_themes WHERE category_id=? AND code=?", (cid, code))
        return jsonify({"items": cs.themes(conn, cid)})


@bp.get("/admin/catalog/categories/<int:cid>/mappings")
@require_auth("admin")
def mappings_get(cid: int):
    with get_db().read_transaction() as conn:
        return jsonify({"items": [dict(r) for r in conn.execute(
            "SELECT source, external_code, external_name FROM category_external_mappings WHERE category_id=? ORDER BY source", (cid,))]})


@bp.put("/admin/catalog/categories/<int:cid>/mappings")
@require_auth("admin")
def mappings_put(cid: int):
    items = _body().get("items")
    if not isinstance(items, list):
        raise ValidationError("items باید فهرست باشد")
    with get_db().write_transaction() as conn:
        _category(conn, cid)
        for it in items:
            if not isinstance(it, dict) or it.get("source") not in _SOURCES:
                raise ValidationError("منبع نگاشت نامعتبر است")
            code, name = _str(it, "external_code", 120) or "", _str(it, "external_name", 200)
            conn.execute("DELETE FROM category_external_mappings WHERE category_id=? AND source=?", (cid, it["source"]))
            conn.execute("INSERT INTO category_external_mappings (category_id, source, external_code, external_name) VALUES (?,?,?,?)",
                         (cid, it["source"], code, name))
        return jsonify({"items": [dict(r) for r in conn.execute(
            "SELECT source, external_code, external_name FROM category_external_mappings WHERE category_id=? ORDER BY source", (cid,))]})


# ── admin: product values, quality, variation check, backfill ──

@bp.get("/admin/catalog/products/<int:mid>/attributes")
@require_auth("admin")
def product_values_get(mid: int):
    with get_db().read_transaction() as conn:
        cid = cs.category_of_master(conn, mid)
        return jsonify({"master_product_id": mid, "category_id": cid, "values": cs.get_values(conn, mid),
                        "spec_groups": cs.spec_groups(conn, mid, cid)})


@bp.put("/admin/catalog/products/<int:mid>/attributes")
@require_auth("admin")
def product_values_put(mid: int):
    d = _body()
    values = d.get("attributes", d)
    with get_db().write_transaction() as conn:
        out = cs.set_values(conn, mid, values, source="admin", category_id=_int(d, "category_id", 1))
        out["quality"] = cq.master_quality(conn, mid)
        return jsonify(out)


@bp.get("/admin/catalog/products/<int:mid>/quality")
@require_auth("admin")
def product_quality(mid: int):
    with get_db().write_transaction() as conn:
        return jsonify(cq.master_quality(conn, mid))


@bp.get("/admin/catalog/quality")
@require_auth("admin")
def quality_list():
    try:
        max_score = int(request.args.get("max_score", 100))
    except ValueError:
        raise ValidationError("max_score نامعتبر است")
    with get_db().read_transaction() as conn:
        rows = conn.execute("""SELECT q.*, m.canonical_name_fa FROM catalog_quality_scores q JOIN master_products m ON m.id=q.master_product_id
                               WHERE q.score <= ? ORDER BY q.score, q.master_product_id LIMIT 500""", (max_score,)).fetchall()
        return jsonify({"items": [{**dict(r), "checklist": json.loads(r["checklist_json"])} for r in rows]})


@bp.get("/admin/catalog/families/<int:fid>/variation-check")
@require_auth("admin")
def family_check(fid: int):
    with get_db().read_transaction() as conn:
        return jsonify(cs.check_family(conn, fid))


@bp.post("/admin/catalog/attributes/backfill")
@require_auth("admin")
def backfill():
    d = request.get_json(silent=True) or {}
    with get_db().write_transaction() as conn:
        return jsonify(cs.backfill(conn, dry_run=bool(d.get("dry_run"))))


@bp.post("/admin/catalog/policies/apply-defaults")
@require_auth("admin")
def apply_defaults():
    with get_db().write_transaction() as conn:
        return jsonify(cq.apply_policy_defaults(conn))
