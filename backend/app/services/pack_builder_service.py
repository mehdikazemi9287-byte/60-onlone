"""Budget-driven pack builder over the REAL catalog.

Given people, an optional budget per person and preferences, returns four honest options:
  A — essentials (one smallest size per available subcategory)
  B — balanced (one mid size per subcategory)
  C — preferred brands / larger sizes
  D — customizable (required items + balanced base, editable)
Prices come only from verified offers. If any item lacks one, the option is "quote required" and no
total is shown; a budget is enforced only when real prices exist.
"""
from __future__ import annotations

from app.core.errors import ValidationError
from app.services import sale_eligibility as se
from app.services import storefront_service as store
from app.services import product_channel_policy as policy
from app.services import text_norm as tn

DEFAULT_CATEGORIES = ("supermarket", "fresh-dairy-frozen--dairy")
OCCASION_CATEGORIES = {"nowruz": ("nuts-local", "gift-seasonal"), "yalda": ("nuts-local", "gift-seasonal"),
                       "ramadan": ("supermarket", "fresh-dairy-frozen", "gift-seasonal"), "livelihood": DEFAULT_CATEGORIES,
                       "office": ("digital--laptop", "digital--monitor", "digital--headphone"), "hospitality": ("nuts-local", "gift-seasonal")}
OCCASION_CATEGORIES.update({key:("gift-seasonal", "nuts-local") for key in ("women_day","men_day","management_gift","employee_gift")})
OCCASION_CATEGORIES["welfare"]=DEFAULT_CATEGORIES
LABELS = {"A": "ضروری و اقتصادی", "B": "ترکیب متعادل", "C": "برندهای ترجیحی و اندازه بزرگ‌تر", "D": "قابل شخصی‌سازی"}


def _size(s) -> float:
    a = s.attributes
    return float(a.get("weight_g") or a.get("volume_ml") or a.get("screen_inch") or a.get("capacity_mah") or 0)


def suggest(conn, data: dict) -> dict:
    people = data.get("people")
    if isinstance(people, bool) or not isinstance(people, int) or not 1 <= people <= 100000:
        raise ValidationError("تعداد نفرات باید بین ۱ و ۱۰۰٬۰۰۰ باشد")
    budget = data.get("budget_per_person_minor")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0):
        raise ValidationError("بودجه هر نفر نامعتبر است")
    occasion = data.get("occasion") or "livelihood"
    for field in ("categories", "required", "excluded", "preferred_brands"):
        if data.get(field) is not None and (not isinstance(data[field], list) or any(not isinstance(x, str) for x in data[field])):
            raise ValidationError("فهرست ترجیحات نامعتبر است")
    cats = tuple(c for c in (data.get("categories") or OCCASION_CATEGORIES.get(occasion, DEFAULT_CATEGORIES)) if isinstance(c, str))[:12]
    required = {x for x in (data.get("required") or []) if isinstance(x, str)}
    excluded = {x for x in (data.get("excluded") or []) if isinstance(x, str)}
    brands = {tn.normalize(b) for b in (data.get("preferred_brands") or []) if isinstance(b, str) and b.strip()}
    catalog = store._load(conn)
    cats_by_id = catalog["cats"]
    excluded_norm = {tn.normalize(e) for e in excluded if e.strip()}
    def is_excluded(s):
        return s.slug in excluded or any(e in tn.normalize(s.title) or e == tn.normalize(s.brand) for e in excluded_norm)
    if any(s.slug in required and is_excluded(s) for s in catalog["skus"]):
        raise ValidationError("کالای الزامی نمی‌تواند در فهرست حذف باشد")
    pool = [s for s in catalog["skus"] if any(c in s.search["path_slugs"] for c in cats) and not is_excluded(s)]
    if not pool:
        raise ValidationError("برای این انتخاب کالای واقعی در کاتالوگ یافت نشد")
    avail = store.availability_map(conn, [s.id for s in pool] + [s.id for s in catalog["skus"] if s.slug in required])

    def leaf(s, level):
        path = store.category_path(cats_by_id, s.category_id)
        nodes = [c for c in path if c["level"] == level] or path[-1:]
        return nodes[-1]["id"] if nodes else 0

    def group(level):
        g: dict = {}
        for s in pool:
            g.setdefault(leaf(s, level), []).append(s)
        # Prefer verified offers when a budget is requested, retaining honest inquiry
        # candidates only for groups without a priced offer.
        return [([s for s in rows if avail.get(s.id, (None, None))[1] is not None] or rows)
                if budget is not None else rows for rows in g.values()]

    must = [s for s in catalog["skus"] if s.slug in required]
    options = {
        "A": [min(g, key=lambda s: (_size(s) or 1e12, s.id)) for g in group("subcategory")][:8],
        "B": [sorted(g, key=lambda s: (_size(s), s.id))[len(g) // 2] for g in group("subcategory")][:8],
        "C": [max(g, key=lambda s: (tn.normalize(s.brand) in brands, _size(s), -s.id)) for g in group("subcategory")][:8],
    }
    options["D"] = list({s.id: s for s in must + options["B"]}.values())
    out = []
    for key, items in options.items():
        items = list({s.id: s for s in must + items}.values()) if key != "D" else items
        lines = []
        for s in items:
            state, price = avail.get(s.id) or store._availability(conn, s.id)
            lines.append({"slug": s.slug, "sku": s.sku, "title_fa": s.title, "brand_fa": s.brand, "variant_label": s.label,
                          "image_url": s.images[0] if s.images else None, "quantity": 1, "unit_price_minor": price,
                          "allowed_channels":list(policy.channels(s.supply_channel)), "availability": state, "required": s.slug in required, "weight_g": s.attributes.get("weight_g")})
        priced = bool(lines) and all(line["unit_price_minor"] is not None for line in lines)
        trimmed = []
        if priced and budget is not None:
            # Drop the costliest optional lines until the real per-person total fits the budget.
            while sum(line["unit_price_minor"] for line in lines) > budget:
                optional = [line for line in lines if not line["required"]]
                if not optional:
                    break
                drop = max(optional, key=lambda line: line["unit_price_minor"])
                lines.remove(drop)
                trimmed.append(drop["title_fa"])
        if not lines:
            continue  # An empty pack is not a free, within-budget recommendation.
        per_person = sum(line["unit_price_minor"] for line in lines) if priced else None
        out.append({
            "allowed_channels":sorted(set.intersection(*[set(line["allowed_channels"]) for line in lines])) if lines else [], "key": key, "label_fa": LABELS[key], "items": lines, "item_count": len(lines),
            "food_weight_g": sum(line["weight_g"] or 0 for line in lines) or None,
            "priced": priced, "price_per_person_minor": per_person, "total_minor": per_person * people if per_person is not None else None,
            "within_budget": (per_person <= budget) if (per_person is not None and budget is not None) else None,
            "trimmed_for_budget": trimmed, "customizable": key == "D",
            "note": None if priced else "برخی اقلام هنوز پیشنهاد تأییدشده فروشنده ندارند؛ قیمت با درخواست استعلام اعلام می‌شود.",
        })
    return {"people": people, "budget_per_person_minor": budget, "occasion": occasion, "categories": list(cats),
            "sales_enabled": se.sales_enabled(), "options": out}
