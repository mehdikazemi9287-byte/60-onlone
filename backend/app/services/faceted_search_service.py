"""Phase 6 — attribute filters and facet counts over typed product_attribute_values (indexed lookups).

Query grammar (storefront list/search): attr.<code>=v1,v2 (OR within an attribute, AND across attributes),
attr.<code>=500..1000 / 0.5kg..1kg / 500.. (ranges for number/measure, canonical unit when no unit),
attr.<code>=بله|1 (boolean), seller_kind=shop,brand, official=1 (brand-owned stores), in_stock=1.
Facet counts are disjunctive: an attribute's own filter is ignored when counting its values.
"""
from __future__ import annotations

from app.core.errors import ValidationError
from app.services import catalog_schema_service as cs
from app.services import text_norm as tn

SELLER_KINDS = ("supplier", "shop", "brand", "partner")
_CHUNK = 900


def _get_all(args, key):
    if hasattr(args, "getlist"):
        return args.getlist(key)
    v = args.get(key)
    return v if isinstance(v, list) else [] if v is None else [v]


def parse_filters(args) -> dict:
    attrs: dict[str, list[str]] = {}
    for key in list(args.keys()):
        if key.startswith("attr.") and len(key) > 5:
            vals = [x.strip() for v in _get_all(args, key) for x in cs.latin_digits(v).split(",") if x.strip()]
            if vals:
                attrs[key[5:]] = vals
    out: dict = {}
    if attrs:
        out["attrs"] = attrs
    kinds = [k.strip() for v in _get_all(args, "seller_kind") for k in str(v).split(",") if k.strip()]
    if kinds:
        bad = [k for k in kinds if k not in SELLER_KINDS]
        if bad:
            raise ValidationError(f"نوع فروشنده «{bad[0]}» نامعتبر است", code="invalid_seller_kind")
        out["seller_kind"] = kinds
    if str(args.get("official") or "").strip() in ("1", "true"):
        out["official"] = True
    if str(args.get("in_stock") or "").strip() in ("1", "true"):
        out["in_stock"] = True
    return out


def request_filters() -> dict:
    try:
        from flask import has_request_context, request
    except ImportError:  # pragma: no cover
        return {}
    return parse_filters(request.args) if has_request_context() else {}


def _ids_query(conn, sql: str, args: tuple) -> set:
    return {r[0] for r in conn.execute(sql, args)}


def _bound(conn, a: dict, text: str) -> int | None:
    if text == "":
        return None
    if a["data_type"] == "measure":
        return cs.parse_measure(conn, a, text)[0]
    return cs._milli(cs._dec(text))


def match_set(conn, a: dict, values: list[str]) -> set:
    aid, dt, name = a["id"], a["data_type"], a["name_fa"]
    base = "SELECT DISTINCT master_product_id FROM product_attribute_values WHERE attribute_id=? AND "
    try:
        if dt in ("enum", "multi_enum"):
            opts = cs.options(conn, aid)
            ids = []
            for v in values:
                o = next((o for o in opts if o["code"] == v or tn.normalize(o["label_fa"]) == tn.normalize(v)), None)
                if not o:
                    raise ValidationError(f"گزینهٔ «{v}» برای فیلتر «{name}» نامعتبر است", code="invalid_attribute_filter")
                ids.append(o["id"])
            return _ids_query(conn, base + f"option_id IN ({','.join('?' * len(ids))})", (aid, *ids))
        if dt in ("number", "integer", "measure"):
            out: set = set()
            for v in values:
                if ".." in v:
                    lo_t, hi_t = v.split("..", 1)
                    lo, hi = _bound(conn, a, lo_t.strip()), _bound(conn, a, hi_t.strip())
                    out |= _ids_query(conn, base + "value_number >= ? AND value_number <= ?",
                                      (aid, lo if lo is not None else -(10 ** 18), hi if hi is not None else 10 ** 18))
                else:
                    out |= _ids_query(conn, base + "value_number = ?", (aid, _bound(conn, a, v)))
            return out
        if dt == "boolean":
            flags = []
            for v in values:
                t = tn.normalize(v).lower()
                if t not in cs.TRUE_WORDS | cs.FALSE_WORDS:
                    raise ValidationError(f"فیلتر «{name}» باید بله یا خیر باشد", code="invalid_attribute_filter")
                flags.append(int(t in cs.TRUE_WORDS))
            return _ids_query(conn, base + f"value_bool IN ({','.join('?' * len(flags))})", (aid, *flags))
        return _ids_query(conn, base + f"value_text IN ({','.join('?' * len(values))})", (aid, *values))
    except (ValueError, ArithmeticError):
        raise ValidationError(f"مقدار فیلتر «{name}» نامعتبر است", code="invalid_attribute_filter")


def attribute_sets(conn, attr_filters: dict) -> dict[str, set]:
    sets = {}
    for code, values in attr_filters.items():
        r = conn.execute("SELECT * FROM attribute_definitions WHERE code=? AND status='active'", (code,)).fetchone()
        if not r:
            raise ValidationError(f"فیلتر ویژگی «{code}» نامعتبر است", code="invalid_attribute_filter")
        sets[code] = match_set(conn, dict(r), values)
    return sets


def seller_sku_ids(conn, kinds: list[str] | None, official: bool) -> set:
    kinds = ["brand"] if official and not kinds else [k for k in (kinds or []) if not official or k == "brand"] or ["__none__"]
    marks = ",".join("?" * len(kinds))
    return _ids_query(conn, f"""SELECT DISTINCT so.product_id FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                                WHERE so.status='active' AND s.status='active' AND s.seller_kind IN ({marks})""", tuple(kinds))


def _rows(conn, attribute_id: int, mids: set):
    mids = list(mids)
    for i in range(0, len(mids), _CHUNK):
        chunk = mids[i:i + _CHUNK]
        yield from conn.execute(f"""SELECT master_product_id, option_id, value_text, value_bool, value_number FROM product_attribute_values
                                   WHERE attribute_id=? AND master_product_id IN ({','.join('?' * len(chunk))})""", (attribute_id, *chunk))


def facets(conn, category_id: int | None, pool: set, sets: dict[str, set], selected: dict | None = None) -> list[dict]:
    if not category_id or not pool:
        return []
    selected = selected or {}
    out = []
    for a in cs.effective_schema(conn, category_id):
        if not a["is_filterable"]:
            continue
        base = set(pool)
        for code, s in sets.items():
            if code != a["code"]:
                base &= s
        if not base:
            continue
        counts: dict = {}
        nums: list[int] = []
        for r in _rows(conn, a["attribute_id"], base):
            if a["data_type"] in ("enum", "multi_enum"):
                k = r["option_id"]
            elif a["data_type"] == "boolean":
                k = bool(r["value_bool"])
            elif r["value_number"] is not None:
                k = r["value_number"]
                nums.append(k)
            else:
                k = r["value_text"]
            counts.setdefault(k, set()).add(r["master_product_id"])
        if not counts:
            continue
        sel = set(selected.get(a["code"], []))
        f = {"code": a["code"], "name_fa": a["name_fa"], "data_type": a["data_type"], "display_group_fa": a["display_group_fa"],
             "unit": a["canonical_unit"], "values": []}
        if a["data_type"] in ("enum", "multi_enum"):
            labels = {o["id"]: o for o in cs.options(conn, a["attribute_id"])}
            for oid, o in labels.items():
                if oid in counts:
                    f["values"].append({"value": o["code"], "label_fa": o["label_fa"], "count": len(counts[oid]), "selected": o["code"] in sel})
        elif a["data_type"] == "boolean":
            for k in (True, False):
                if k in counts:
                    f["values"].append({"value": "1" if k else "0", "label_fa": "بله" if k else "خیر", "count": len(counts[k]),
                                        "selected": ("1" if k else "0") in sel})
        elif nums:
            f["min"], f["max"] = cs.fmt_milli(min(nums)).translate(_LAT), cs.fmt_milli(max(nums)).translate(_LAT)
            for k, ms in sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:12]:
                plain = cs.fmt_milli(k).translate(_LAT)
                label = cs._display_measure(conn, a["unit_kind"], k) if a["data_type"] == "measure" else cs.fmt_milli(k)
                f["values"].append({"value": plain, "label_fa": label, "count": len(ms), "selected": plain in sel})
            f["values"].sort(key=lambda v: float(v["value"]))
        else:
            for k, ms in sorted(counts.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))[:20]:
                f["values"].append({"value": k, "label_fa": k, "count": len(ms), "selected": k in sel})
        out.append(f)
    return out


_LAT = str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")


def apply(conn, hits: list, filters: dict, category_id: int | None, availability_map=None) -> tuple[list, list]:
    """Filter storefront hits [(score, sku)] by attribute/seller/stock filters and build attribute facets."""
    filters = filters or {}
    out = list(hits)
    if filters.get("seller_kind") or filters.get("official"):
        skus = seller_sku_ids(conn, filters.get("seller_kind"), bool(filters.get("official")))
        out = [(sc, s) for sc, s in out if s.id in skus]
    if filters.get("in_stock") and availability_map is not None:
        avail = availability_map(conn, [s.id for _, s in out])
        out = [(sc, s) for sc, s in out if avail.get(s.id, ("no_offer",))[0] == "purchasable"]
    pool = {s.variant_id for _, s in out}
    sets = attribute_sets(conn, filters.get("attrs", {})) if filters.get("attrs") else {}
    allowed = set(pool)
    for s in sets.values():
        allowed &= s
    return [(sc, s) for sc, s in out if s.variant_id in allowed], facets(conn, category_id, pool, sets, filters.get("attrs"))
