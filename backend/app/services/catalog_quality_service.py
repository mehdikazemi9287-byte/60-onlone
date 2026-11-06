"""Phase 6 — listing policies (inherited per field), listing-quality score with a Persian checklist,
the offer gate (CATALOG_ENFORCE_REQUIRED=1 blocks; default warn-only), unit pricing and category SEO."""
from __future__ import annotations

import json
import os
import re

from app.core.errors import ValidationError
from app.services import catalog_schema_service as cs
from app.services import text_norm as tn

POLICY_FIELDS = ("required_attribute_codes", "min_images", "title_template", "max_title_length", "banned_words", "withdrawal_exempt_default",
                 "requires_cold_chain", "is_perishable", "is_fragile", "is_hazardous", "tax_category", "return_window_days",
                 "commission_hint_bps", "meta_title_template", "meta_description_template")
DEFAULT_POLICY = {"min_images": 1, "max_title_length": 150, "banned_words": "", "required_attribute_codes": "", "withdrawal_exempt_default": "none",
                  "requires_cold_chain": 0, "is_perishable": 0, "is_fragile": 0, "is_hazardous": 0, "tax_category": "STANDARD",
                  "return_window_days": 7, "commission_hint_bps": None, "title_template": "{product_type} {brand} {model}",
                  "meta_title_template": "خرید {name} | شصت آنلاین", "meta_description_template": "خرید آنلاین {name} از دسته {category} در شصت آنلاین."}
# Score weights (sum 100), Digikala/Amazon style: required specs dominate, then images, title, recommended specs, text.
W_REQUIRED, W_IMAGES, W_TITLE, W_RECOMMENDED, W_BRAND, W_DESC = 45, 20, 15, 10, 5, 5


def enforce_required() -> bool:
    return os.environ.get("CATALOG_ENFORCE_REQUIRED", "0").strip() in ("1", "true", "yes")


def effective_policy(conn, category_id: int | None) -> dict:
    out = dict(DEFAULT_POLICY)
    out["sources"] = {}
    if category_id is None:
        return out
    for node in cs.ancestors(conn, category_id):
        r = conn.execute("SELECT * FROM category_listing_policies WHERE category_id=?", (node["id"],)).fetchone()
        if r:
            for f in POLICY_FIELDS:
                if r[f] is not None:
                    out[f] = r[f]
                    out["sources"][f] = node["slug"]
    for f in ("requires_cold_chain", "is_perishable", "is_fragile", "is_hazardous"):
        out[f] = bool(out[f])
    out["banned_words"] = [w.strip() for w in re.split(r"[,،\n]", out["banned_words"] or "") if w.strip()]
    out["required_attribute_codes"] = [c.strip() for c in (out["required_attribute_codes"] or "").split(",") if c.strip()]
    return out


def _fmt_measure(conn, code: str, milli_values: dict) -> str:
    if code not in milli_values:
        return ""
    kind = {"weight_g": "weight", "volume_ml": "volume"}.get(code)
    return cs._display_measure(conn, kind, milli_values[code]) if kind else cs.fmt_milli(milli_values[code])


def render_title(conn, template: str, *, category: dict, brand: str | None, model: str | None, values: dict, milli: dict, labels: dict) -> str:
    def sub(m):
        k = m.group(1)
        if k == "product_type":
            return category["name_fa"]
        if k == "brand":
            return brand or ""
        if k == "model":
            return model or ""
        if k in ("weight", "volume"):
            return _fmt_measure(conn, f"{k}_g" if k == "weight" else "volume_ml", milli)
        if k in labels:
            return labels[k]
        v = values.get(k)
        return "" if v is None else cs.fa_digits(v if not isinstance(v, list) else "، ".join(map(str, v)))
    return re.sub(r"\s+", " ", re.sub(r"\{(\w+)\}", sub, template or "")).strip()


def evaluate(conn, *, category_id: int, title: str | None, brand: str | None, model: str | None = None, images: list | None = None,
             description: str | None = None, attributes: dict | None = None, stored_values: dict | None = None) -> dict:
    """Score + checklist for a draft (seller validate) or a stored master (stored_values = typed values already saved)."""
    category = cs.ancestors(conn, category_id)[-1]
    policy = effective_policy(conn, category_id)
    res = cs.validate_attributes(conn, category_id, attributes or {})
    schema = res["schema"]
    by_code = {a["code"]: a for a in schema}
    values = dict(stored_values or {})
    labels: dict = {}
    milli: dict = {}
    for code, rows in res["rows"].items():
        a = by_code[code]
        r0 = rows[0]
        if a["data_type"] == "multi_enum":
            values[code] = [r["value_text"] for r in rows]
        elif r0["value_number"] is not None:
            values[code] = cs.fmt_milli(r0["value_number"])
        elif r0["value_bool"] is not None:
            values[code] = bool(r0["value_bool"])
        else:
            values[code] = r0["value_text"]
        if rows[0]["value_number"] is not None:
            milli[code] = rows[0]["value_number"]
        if a["options"]:
            labels[code] = "، ".join(next((o["label_fa"] for o in a["options"] if o["code"] == r["value_text"]), r["value_text"]) for r in rows)
    if stored_values is not None and "_milli" in stored_values:
        milli = {**stored_values.pop("_milli"), **milli}
        values.pop("_milli", None)
    for code, v in values.items():
        a = by_code.get(code)
        if a and a["options"] and code not in labels:
            vs = v if isinstance(v, list) else [v]
            labels[code] = "، ".join(next((o["label_fa"] for o in a["options"] if o["code"] == x), str(x)) for x in vs)
    checklist: list[dict] = []

    def check(key, ok, message, weight, kind="required"):
        checklist.append({"key": key, "ok": bool(ok), "message_fa": message, "weight": weight, "kind": kind})

    required = [a for a in schema if a["required"]] + [by_code[c] for c in policy["required_attribute_codes"] if c in by_code and not by_code[c]["required"]]
    missing = [a for a in required if a["code"] not in values]
    for a in required:
        check(f"attr:{a['code']}", a["code"] in values, f"مشخصهٔ الزامی «{a['name_fa']}» را وارد کنید", 0)
    recommended = [a for a in schema if not a["required"] and (a["is_filterable"] or a["is_searchable"]) and a not in required]
    rec_missing = [a for a in recommended if a["code"] not in values]
    for a in rec_missing[:8]:
        check(f"rec:{a['code']}", False, f"افزودن «{a['name_fa']}» به یافته‌شدن کالا در فیلترها کمک می‌کند", 0, "recommended")
    for e in res["errors"]:
        check(f"invalid:{e['attribute']}", False, e["message"], 0)
    n_img = len([i for i in (images or []) if i])
    min_img = int(policy["min_images"] or 0)
    check("images", n_img >= min_img, f"دست‌کم {cs.fa_digits(min_img)} تصویر با زمینهٔ سفید لازم است (اکنون {cs.fa_digits(n_img)})", W_IMAGES)
    t = (title or "").strip()
    norm_t = tn.normalize(t)
    banned = [w for w in policy["banned_words"] if tn.normalize(w) and tn.normalize(w) in norm_t]
    title_problems = []
    if not t:
        title_problems.append("عنوان کالا خالی است")
    if len(t) > int(policy["max_title_length"]):
        title_problems.append(f"عنوان بیش از {cs.fa_digits(policy['max_title_length'])} نویسه است")
    if banned:
        title_problems.append(f"واژه‌های غیرمجاز در عنوان: {'، '.join(banned)}")
    if brand and t and tn.normalize(brand) not in norm_t:
        title_problems.append("نام برند در عنوان نیامده است")
    check("title", not title_problems, "؛ ".join(title_problems) or "عنوان مطابق الگوی دسته است", W_TITLE)
    check("brand", bool((brand or "").strip()), "برند کالا را مشخص کنید (برای کالای بی‌برند «متفرقه»)", W_BRAND)
    check("description", len((description or "").strip()) >= 50, "توضیحات کالا دست‌کم ۵۰ نویسه باشد", W_DESC)
    req_score = W_REQUIRED if not required else W_REQUIRED * (len(required) - len(missing)) // len(required)
    rec_score = W_RECOMMENDED if not recommended else W_RECOMMENDED * (len(recommended) - len(rec_missing)) // len(recommended)
    img_score = W_IMAGES if n_img >= min_img else (W_IMAGES * n_img // min_img if min_img else W_IMAGES)
    score = req_score + rec_score + img_score + sum(c["weight"] for c in checklist if c["ok"] and c["key"] in ("title", "brand", "description"))
    if res["errors"]:
        score -= min(20, 5 * len(res["errors"]))
    score = max(0, min(100, score))
    suggested = render_title(conn, policy["title_template"], category=category, brand=brand, model=model, values=values, milli=milli, labels=labels)
    return {"score": score, "grade": "A" if score >= 85 else "B" if score >= 65 else "C" if score >= 40 else "D",
            "missing_required": [a["code"] for a in missing], "errors": res["errors"],
            "checklist": [c for c in checklist if not c["ok"]] + [c for c in checklist if c["ok"]],
            "suggested_title": suggested, "category": {"id": category["id"], "slug": category["slug"], "name_fa": category["name_fa"]},
            "policy": {k: policy[k] for k in ("min_images", "max_title_length", "title_template", "withdrawal_exempt_default", "requires_cold_chain",
                                             "is_perishable", "is_fragile", "is_hazardous", "tax_category", "return_window_days", "commission_hint_bps")}}


def master_quality(conn, master_product_id: int, *, store: bool = True) -> dict:
    m = conn.execute("SELECT id, canonical_name_fa, brand, model, variant, description_fa, image_urls_json FROM master_products WHERE id=?",
                     (master_product_id,)).fetchone()
    if not m:
        from app.core.errors import NotFoundError
        raise NotFoundError("محصول یافت نشد", code="product_not_found")
    cid = cs.category_of_master(conn, master_product_id)
    if cid is None:
        return {"master_product_id": master_product_id, "score": 0, "missing_required": [], "errors": [], "category": None,
                "checklist": [{"key": "category", "ok": False, "message_fa": "دستهٔ کالا را مشخص کنید", "weight": 0, "kind": "required"}]}
    try:
        images = [u for u in json.loads(m["image_urls_json"] or "[]") if isinstance(u, str)]
    except ValueError:
        images = []
    stored = cs.get_values(conn, master_product_id)
    stored["_milli"] = cs.raw_milli(conn, master_product_id)
    out = evaluate(conn, category_id=cid, title=m["canonical_name_fa"], brand=m["brand"], model=m["model"] or m["variant"], images=images,
                   description=m["description_fa"], stored_values=stored)
    out["master_product_id"] = master_product_id
    if store:
        conn.execute("DELETE FROM catalog_quality_scores WHERE master_product_id=?", (master_product_id,))
        conn.execute("INSERT INTO catalog_quality_scores (master_product_id, category_id, score, missing_required, checklist_json) VALUES (?,?,?,?,?)",
                     (master_product_id, cid, out["score"], len(out["missing_required"]),
                      json.dumps([c for c in out["checklist"] if not c["ok"]], ensure_ascii=False)))
    return out


def offer_gate(conn, product_id: int) -> list[dict]:
    """Missing required attributes of the SKU's master. Enforced → ValidationError; otherwise returns warnings."""
    r = conn.execute("SELECT master_product_id FROM products WHERE id=?", (product_id,)).fetchone()
    if not r or r["master_product_id"] is None:
        return []
    q = master_quality(conn, r["master_product_id"], store=False)
    warnings = [c for c in q["checklist"] if not c["ok"] and c["kind"] == "required" and c["key"].startswith(("attr:", "category"))]
    if warnings and enforce_required():
        raise ValidationError("مشخصات الزامی کالا کامل نیست؛ پیش از فعال‌سازی پیشنهاد آن‌ها را تکمیل کنید",
                              code="catalog_required_attributes_missing", details={"checklist": warnings, "score": q["score"]})
    return warnings


# ── unit price & SEO ──

def unit_price(conn, master_product_id: int, price_minor: int | None) -> dict | None:
    """Comparison price per kg / liter / piece (EU-style), integer Rial, rounded half-up."""
    if not price_minor:
        return None
    milli = cs.raw_milli(conn, master_product_id)
    pack = max(1, (milli.get("pack_count") or 1000) // 1000)
    for code, per, label in (("weight_g", 1_000_000, "هر کیلوگرم"), ("volume_ml", 1_000_000, "هر لیتر")):
        if milli.get(code):
            total = milli[code] * pack
            return {"basis": "kg" if code == "weight_g" else "l", "label_fa": label,
                    "price_minor": (price_minor * per + total // 2) // total, "quantity_milli": total}
    if pack > 1:
        return {"basis": "pcs", "label_fa": "هر عدد", "price_minor": (price_minor + pack // 2) // pack, "quantity_milli": pack * 1000}
    return None


def _fill(template: str, ctx: dict) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\{(\w+)\}", lambda m: str(ctx.get(m.group(1), "")), template or "")).strip()


def seo(conn, *, category_id: int | None, path: list[dict], name: str, brand: str | None, slug: str, specs: list[dict],
        price_minor: int | None, base_url: str = "") -> dict:
    policy = effective_policy(conn, category_id)
    leaf = path[-1]["name_fa"] if path else ""
    ctx = {"name": name, "category": leaf, "brand": brand or ""}
    canonical_path = "/" + "/".join(["c"] + [c["slug"] for c in path]) if path else "/"
    crumbs = [{"@type": "ListItem", "position": i + 1, "name": c["name_fa"], "item": f"{base_url}/c/{c['slug']}"} for i, c in enumerate(path)]
    crumbs.append({"@type": "ListItem", "position": len(crumbs) + 1, "name": name, "item": f"{base_url}/p/{slug}"})
    props = [{"@type": "PropertyValue", "name": i["label_fa"], "value": i["value_fa"]} for g in specs for i in g["items"]]
    product = {"@context": "https://schema.org", "@type": "Product", "name": name, "category": " > ".join(c["name_fa"] for c in path),
               "additionalProperty": props}
    if brand:
        product["brand"] = {"@type": "Brand", "name": brand}
    if price_minor:
        product["offers"] = {"@type": "Offer", "priceCurrency": "IRR", "price": str(price_minor)}
    return {"meta_title": _fill(policy["meta_title_template"], ctx)[:70], "meta_description": _fill(policy["meta_description_template"], ctx)[:160],
            "canonical_path": f"/p/{slug}", "category_canonical_path": canonical_path,
            "breadcrumb_list": {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs}, "product_jsonld": product}


def category_seo(conn, category_id: int) -> dict:
    chain = cs.ancestors(conn, category_id)
    policy = effective_policy(conn, category_id)
    name = chain[-1]["name_fa"]
    return {"meta_title": _fill("خرید {category} | قیمت و مشخصات در شصت آنلاین", {"category": name})[:70],
            "meta_description": _fill(policy["meta_description_template"], {"name": name, "category": name})[:160],
            "canonical_path": "/c/" + "/".join(c["slug"] for c in chain),
            "breadcrumbs": [{"slug": c["slug"], "name_fa": c["name_fa"], "level": c["level"]} for c in chain]}


def apply_policy_defaults(conn) -> dict:
    """Fill products.withdrawal_exempt_reason where still NULL from the category policy (never overwrites)."""
    n = 0
    for p in conn.execute("SELECT id, category_id FROM products WHERE withdrawal_exempt_reason IS NULL").fetchall():
        reason = effective_policy(conn, p["category_id"])["withdrawal_exempt_default"] if p["category_id"] else "none"
        if reason and reason != "none":
            conn.execute("UPDATE products SET withdrawal_exempt_reason=? WHERE id=? AND withdrawal_exempt_reason IS NULL", (reason, p["id"]))
            n += 1
    return {"updated": n}


def product_detail_extras(conn, *, master_product_id: int, category_id: int | None, path: list[dict], name: str, brand: str | None,
                          slug: str, price_minor: int | None) -> dict:
    """Additive product-detail fields: grouped specs table, unit price, SEO/schema.org data."""
    groups = cs.spec_groups(conn, master_product_id, category_id)
    return {"spec_groups": groups, "unit_price": unit_price(conn, master_product_id, price_minor),
            "seo": seo(conn, category_id=category_id, path=path, name=name, brand=brand, slug=slug, specs=groups, price_minor=price_minor)}
