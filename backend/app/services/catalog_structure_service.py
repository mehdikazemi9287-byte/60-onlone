"""Derive the marketplace structure from real catalog rows. Idempotent; never invents products or prices.

* Taxonomy: departments group the existing categories; subcategory / product-type nodes are
  created only when at least one REAL product matches their rule.
* Families (Product): real master_products whose names differ only by measure/size words
  (e.g. «برنج هاشمی ممتاز طبیعت 900 گرم / 2.5 کیلوگرم») become variants of one family.
* SKU: every real variant gets exactly one storefront `products` row (price column unused: 0).
  Visibility follows the existing publication rules; nothing hidden becomes visible here.
"""
from __future__ import annotations

import json
import re

from app.services import text_norm as tn

DEPARTMENTS = [
    ("dept-supermarket", "سوپرمارکت", ["supermarket", "protein-fresh", "fresh-dairy-frozen", "nuts-local"]),
    ("dept-digital", "کالای دیجیتال", ["digital", "mobile", "laptop", "network"]),
    ("dept-home", "خانه و لوازم خانگی", ["appliances", "appliance", "home-kitchen"]),
    ("dept-office", "اداری و سازمانی", ["office-org", "office", "books-stationery"]),
    ("dept-health", "سلامت، زیبایی و کودک", ["beauty-health", "mother-child-toys"]),
    ("dept-lifestyle", "مد، ورزش و خودرو", ["fashion", "sports-camping", "auto-tools"]),
    ("dept-gift", "هدیه و مناسبت", ["gift-seasonal"]),
]

# category → [(sub_key, sub_name, sub_keywords, [(type_key, type_name, type_keywords)])]; first match wins.
RULES = {
    "supermarket": [
        ("baby-food", "غذای کودک", ["غذای کودک"], []),  # before rice: «فرنی برنج»
        ("ready-food", "ساندویچ و صبحانهٔ آماده", ["ساندویچ", "جعبه صبحانه"], []),  # before rice: «دسر شیربرنج»
        ("rice", "برنج", ["برنج"], [("hashemi", "برنج هاشمی", ["هاشمی"]), ("anbarbu", "برنج عنبربو", ["عنبربو"]),
                                     ("second-crop", "برنج کشت دوم", ["کشت دوم"]), ("imported", "برنج خارجی", ["پاکستانی", "هندی", "تایلندی"])]),
        ("oil", "روغن خوراکی", ["روغن"], [("semi-solid", "روغن نیمه‌جامد", ["نیمه جامد"]), ("frying", "روغن سرخ‌کردنی", ["سرخ کردنی"]),
                                         ("liquid", "روغن مایع", ["افتابگردان", "سویا", "خانوار", "مایع"])]),
        ("baking", "مواد قنادی و پخت", ["روکش کیک", "فیلینگ", "filling", "سکه ای", "اسلب", "پودر کیک", "پودر مافین", "پودر کاکائو",
                                         "پودر ردولوت", "گلیز", "ویوافیل", "کرمفیل", "مینارین", "اپتیمم"], []),
        ("breakfast", "مربا، عسل و صبحانه", ["مربا", "عسل تک", "حلوا", "شکلات صبحانه", "کرم کاکائو"], []),
        ("chocolate", "شکلات، ویفر و تنقلات", ["شکلات", "ویفر", "وافل", "مینی کن"], []),
        ("sauces", "سس و چاشنی", ["سس "], []),
        ("beverages", "نوشیدنی", ["مالت", "ماءالشعیر", "ماء الشعیر", "نکتار", "لاکی", "نوشیدنی", "نوشامیوه", "آب کودکان"],
         [("malt", "ماءالشعیر", ["مالت", "ماءالشعیر", "ماء الشعیر"]), ("juice", "آبمیوه و نکتار", ["نکتار", "لاکی فروت", "آب کودکان"])]),
        ("water", "آب آشامیدنی", ["آب آشامیدنی"], []),
    ],
    "protein-fresh": [
        ("processed", "فرآورده‌های گوشتی", ["سوسیس", "کالباس", "کلاباس", "همبرگر", "برگر", "هات داگ", "ژامبون", "بیکن", "پارما", "کوکتل", "دونر"],
         [("sausage", "سوسیس", ["سوسیس", "هات داگ", "کوکتل"]), ("cold-cut", "کالباس", ["کالباس", "کلاباس", "ژامبون", "بیکن", "پارما"]),
          ("burger", "همبرگر", ["برگر"]), ("doner", "دونر کباب", ["دونر"])]),
        ("fish", "ماهی", ["ماهی", "قزل", "کیلکا"], [("salmon", "ماهی آزاد", ["ازاد"]), ("trout", "ماهی قزل‌آلا", ["قزل"])]),
        ("red-meat", "گوشت قرمز", ["گوساله", "گوسفند"], [("veal", "گوشت گوساله", ["گوساله"]), ("lamb", "گوشت گوسفند", ["گوسفند"])]),
        ("poultry", "مرغ", ["مرغ"], []),
    ],
    "fresh-dairy-frozen": [
        ("ice-cream", "بستنی", ["بستنی"], []),
        ("juice", "آبمیوه و نوشیدنی", ["ابمیوه", "سولاته"], []),
        ("frozen", "منجمد و غذای آماده", ["منجمد", "IQF", "اسفناج", "شوید", "ذرت", "سبزیجات", "لوبیا سبز", "نخود فرنگی", "باقال", "سبزی ",
                                         "جعفری", "کرفس", "سیب زمینی", "کوکو", "شامی", "کتلت", "فلافل", "میگو", "شنیسل", "ناگت", "کنتاکی",
                                         "کوردن", "کراکت", "سوخاری", "پیتزا", "پروموپک"],
         [("pizza", "پیتزا", ["پیتزا", "پروموپک"]), ("vegetables", "سبزیجات منجمد", ["اسفناج", "شوید", "ذرت", "سبزیجات", "لوبیا سبز",
          "نخود فرنگی", "باقال", "سبزی پلو", "سبزی قورمه", "سبزی آش", "سبزی سوپ", "جعفری", "کرفس", "آلبالو", "خلال", "نیمه آماده"]),
          ("ready-meals", "غذای آماده", ["کوکو", "شامی", "کتلت", "فلافل", "میگو", "شنیسل", "ناگت", "کنتاکی", "کوردن", "کراکت", "سوخاری"])]),
        ("spread", "کره گیاهی و اسپرد", ["مارگارین", "اسپرید"], []),
        ("dairy", "لبنیات", ["شیر", "ماست", "پنیر", "خامه", "کره", "دوغ", "دسر", "پودینگ", "پاناکوتا", "کشک", "پروشیک", "ماسکارپونه", "تاپینگ"],
         [("dessert", "دسر و پودینگ", ["دسر", "پودینگ", "پاناکوتا"]), ("kashk", "کشک", ["کشک"]),
          ("milk", "شیر", ["شیر ", "پروشیک"]), ("yogurt", "ماست", ["ماست"]), ("cheese", "پنیر", ["پنیر", "ماسکارپونه", "تاپینگ"]), ("cream", "خامه", ["خامه"]),
          ("butter", "کره", ["کره"]), ("doogh", "دوغ", ["دوغ"])]),
    ],
    "nuts-local": [
        ("spread", "معجون و کرم مغزها", ["معجون"], []),
        ("seeds", "تخمه و نخودچی", ["تخمه", "نخودچی"], []),
        ("pistachio", "پسته", ["پسته"], []),
        ("mixed-nuts", "آجیل", ["اجیل"], []),
    ],
    "gift-seasonal": [
        ("herbal", "دمنوش", ["دمنوش"], []),
        ("gift-basket", "سبد هدیه", ["کادویی", "سبد"], []),
    ],
    "appliances": [
        ("fridge", "یخچال و فریزر", ["یخچال"], []), ("washer", "ماشین لباسشویی", ["لباسشویی"], []),
        ("tv", "تلویزیون", ["تلویزیون"], []), ("vacuum", "جاروبرقی", ["جارو"], []), ("kettle", "کتری برقی", ["کتری"], []),
    ],
    "digital": [
        ("phone", "گوشی موبایل", ["گوشی"], []), ("laptop", "لپ‌تاپ", ["لپ تاپ"], []), ("tablet", "تبلت", ["تبلت"], []),
        ("headphone", "هدفون", ["هدفون"], []), ("monitor", "مانیتور", ["مانیتور"], []), ("powerbank", "پاوربانک", ["پاوربانک"], []),
    ],
    "mobile": [("tablet", "تبلت", ["tab"], []), ("phone", "گوشی موبایل", ["galaxy", "گوشی"], [])],
    "network": [("router", "روتر", ["mikrotik", "روتر"], [])],
}

_RAW_MEASURE = re.compile(r"[\d۰-۹٠-٩]+(?:[.٫][\d۰-۹٠-٩]+)?\s*(?:کیلو\s?گرم(?:ی)?|کیلویی|کیلو|گرم(?:ی)?|میلی\s?لیتر(?:ی)?|میلی‌لیتر(?:ی)?|لیتر(?:ی)?|اینچ(?:ی)?|kg|gr|ml|L\b|inch)", re.I)
FA_DIGITS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")


def _fa(n) -> str:
    return (f"{n:g}" if isinstance(n, float) else str(n)).translate(FA_DIGITS)


def variant_label(attrs: dict) -> str | None:
    parts = []
    if "size_name" in attrs:
        parts.append({"small": "کوچک", "medium": "متوسط", "large": "بزرگ"}[attrs["size_name"]])
    w = attrs.get("weight_g")
    if w:
        parts.append(f"{_fa(w / 1000)} کیلوگرم" if w >= 1000 else f"{_fa(w)} گرم")
    v = attrs.get("volume_ml")
    if v:
        parts.append(f"{_fa(v / 1000)} لیتر" if v >= 1000 else f"{_fa(v)} میلی‌لیتر")
    if attrs.get("screen_inch"):
        parts.append(f"{_fa(attrs['screen_inch'])} اینچ")
    if attrs.get("capacity_mah"):
        parts.append(f"{_fa(attrs['capacity_mah'])} میلی‌آمپر ساعت")
    if attrs.get("model"):
        parts.append(attrs["model"])
    return " · ".join(parts) or None


def attributes(row) -> dict:
    attrs = {}
    for src in (row["canonical_name_fa"], row["size_label"], row["net_quantity"]):
        for k, v in tn.measures(src).items():
            attrs.setdefault(k, v)
    for word, key in tn.SIZE_WORDS.items():
        if word in tn.tokens(row["canonical_name_fa"]):
            attrs["size_name"] = key
    if row["variant"]:
        attrs["model"] = row["variant"]
    if row["unit"]:
        attrs["unit"] = row["unit"]
    return attrs


def family_title(title: str) -> str:
    t = _RAW_MEASURE.sub(" ", title)
    t = " ".join(w for w in t.split() if w not in tn.SIZE_WORDS)
    return re.sub(r"\s+", " ", t).strip()


# (category, sub_key) → words that rule a product out of that subcategory.
EXCLUDE = {("fresh-dairy-frozen", "frozen"): ["تاپینگ", "پنیر پیتزا", "پنیر پستو"]}


def _classify(category: str, name: str):
    norm = " " + tn.normalize(name) + " "
    for sub_key, sub_name, sub_kw, types in RULES.get(category, []):
        if any(tn.normalize(k) in norm or k in norm for k in EXCLUDE.get((category, sub_key), [])):
            continue
        if any(tn.normalize(k) in norm or k in norm for k in sub_kw):
            for t_key, t_name, t_kw in types:
                if any(k in norm or tn.normalize(k) in norm for k in t_kw):
                    return (sub_key, sub_name), (t_key, t_name)
            return (sub_key, sub_name), None
    return None, None


def _node(conn, slug, name, parent_id, level, sort=0) -> int:
    row = conn.execute("SELECT id,admin_managed FROM categories WHERE slug=?", (slug,)).fetchone()
    if row:
        if not row["admin_managed"]:
            conn.execute("UPDATE categories SET name_fa=?, parent_id=?, level=? WHERE id=?", (name, parent_id, level, row["id"]))
        return row["id"]
    return conn.execute("INSERT INTO categories (slug, name_fa, parent_id, sort_order, level) VALUES (?,?,?,?,?)",
                        (slug, name, parent_id, sort, level)).lastrowid


def family_group_key(row) -> str:
    return f"{tn.normalize(row['brand'])}|{row['category']}|{tn.strip_measures(row['canonical_name_fa'])}"


def initialize_family_keys(conn) -> None:
    """Prepare legacy allocation only; no taxonomy, SKU, attributes or visibility writes."""
    fam_keys = {}
    for member in conn.execute("SELECT id, brand, category, canonical_name_fa, family_id FROM master_products WHERE provenance='real' AND status<>'merged' ORDER BY id"):
        fam_keys.setdefault(family_group_key(member), []).append(member)
    # Initialize legacy allocations before an identity editor changes membership.
    # Persist the key so a moved first variant cannot reuse its former family's slug.
    family_members = {}
    for key, members in fam_keys.items():
        for member in members:
            if member["family_id"]:
                family_members.setdefault(member["family_id"], []).append((key, member["id"]))
    for family_id, members in sorted(family_members.items()):
        family = conn.execute("SELECT provenance, grouping_key FROM product_families WHERE id=?", (family_id,)).fetchone()
        if not family or family["provenance"] != "real" or family["grouping_key"] is not None:
            continue
        counts = {}
        for key, mid in members:
            count, first_id = counts.get(key, (0, mid))
            counts[key] = (count + 1, min(first_id, mid))
        key = min(counts, key=lambda k: (-counts[k][0], counts[k][1], k))
        if not conn.execute("SELECT 1 FROM product_families WHERE grouping_key=? AND provenance='real'", (key,)).fetchone():
            conn.execute("UPDATE product_families SET grouping_key=? WHERE id=?", (key, family_id))


def apply(conn, create_skus: bool = True, *, group_keys: frozenset[str] | None = None) -> dict:
    """Rebuild taxonomy, families, variant attributes and (unless create_skus=False) SKUs from real master products.
    Importers call it with create_skus=False: the storefront SKU is created only at review → publish."""
    stats = {"departments": 0, "subcategories": 0, "product_types": 0, "families": 0, "multi_variant_families": 0,
             "variants": 0, "skus_created": 0}
    cats = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM categories WHERE level='category'")}
    if group_keys is None:
        for i, (slug, name, members) in enumerate(DEPARTMENTS):
            dept = _node(conn, slug, name, None, "department", i)
            stats["departments"] += 1
            for m in members:
                if m in cats:
                    conn.execute("UPDATE categories SET parent_id=? WHERE id=? AND admin_managed=0", (dept, cats[m]))
    real = conn.execute("""SELECT * FROM master_products WHERE provenance='real' AND status<>'merged' ORDER BY id""").fetchall()
    fam_keys: dict[str, list] = {}
    leaf_of: dict[int, int] = {}
    for row in real:
        key = family_group_key(row)
        if group_keys is not None and key not in group_keys:
            continue
        cat_id = cats.get(row["category"])
        leaf = cat_id
        sub, typ = _classify(row["category"], row["canonical_name_fa"])
        if cat_id and sub:
            s_id = _node(conn, f"{row['category']}--{sub[0]}", sub[1], cat_id, "subcategory")
            leaf = s_id
            if typ:
                leaf = _node(conn, f"{row['category']}--{sub[0]}--{typ[0]}", typ[1], s_id, "product_type")
        leaf_of[row["id"]] = leaf
        key = family_group_key(row)
        fam_keys.setdefault(key, []).append(row)
    stats["subcategories"] = conn.execute("SELECT COUNT(*) FROM categories WHERE level='subcategory'").fetchone()[0]
    stats["product_types"] = conn.execute("SELECT COUNT(*) FROM categories WHERE level='product_type'").fetchone()[0]
    if group_keys is None:
        initialize_family_keys(conn)
    for key, rows in fam_keys.items():
        first = rows[0]
        slug = f"f-{first['public_product_id']}"
        title = family_title(min((r["canonical_name_fa"] for r in rows), key=len)) if len(rows) > 1 else first["canonical_name_fa"]
        fam = conn.execute("SELECT id FROM product_families WHERE grouping_key=? AND provenance='real'", (key,)).fetchone()
        if not fam:
            legacy = conn.execute("SELECT id, grouping_key, provenance FROM product_families WHERE slug=?", (slug,)).fetchone()
            if legacy and legacy["grouping_key"] is None and legacy["provenance"] == "real" and not conn.execute("SELECT 1 FROM master_products WHERE family_id=?", (legacy["id"],)).fetchone():
                conn.execute("UPDATE product_families SET grouping_key=? WHERE id=?", (key, legacy["id"]))
                fam = legacy
            elif legacy:
                import hashlib
                slug = slug + "-" + hashlib.sha256(key.encode()).hexdigest()

        if fam:
            fam_id = fam["id"]
            conn.execute("UPDATE product_families SET title_fa=?, brand=?, category_id=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                         (title, first["brand"], leaf_of[first["id"]], fam_id))
        else:
            fam_id = conn.execute("INSERT INTO product_families (slug, title_fa, brand, category_id, provenance, grouping_key) VALUES (?,?,?,?, 'real',?)",
                                  (slug, title, first["brand"], leaf_of[first["id"]], key)).lastrowid
        stats["families"] += 1
        stats["multi_variant_families"] += len(rows) > 1
        for r in rows:
            attrs = attributes(r)
            conn.execute("UPDATE master_products SET family_id=?, attributes_json=?, variant_label=? WHERE id=?",
                         (fam_id, json.dumps(attrs, ensure_ascii=False, sort_keys=True), variant_label(attrs), r["id"]))
            stats["variants"] += 1
            if create_skus:
                stats["skus_created"] += _ensure_sku(conn, r, cats)
    return stats


def _ensure_sku(conn, row, cats) -> int:
    if conn.execute("SELECT 1 FROM products WHERE master_product_id=?", (row["id"],)).fetchone():
        return 0
    cat_id = cats.get(row["category"])
    if not cat_id:
        return 0
    pub = conn.execute("SELECT slug, is_visible FROM catalog_publications WHERE master_product_id=?", (row["id"],)).fetchone()
    slug = pub["slug"] if pub else f"p-{row['public_product_id']}"
    visible = 1 if (pub and pub["is_visible"]) else 0
    conn.execute(
        """INSERT INTO products (slug, sku, title_fa, description_fa, brand_fa, category_id, base_price_minor, currency,
               is_active, master_product_id, provenance) VALUES (?,?,?,?,?,?,0,'IRR',?,?,'real')""",
        (slug, f"60-{row['id']:06d}", row["canonical_name_fa"], row["description_fa"] or "", row["brand"] or "", cat_id,
         visible, row["id"]))
    return 1


# ── Review → publish (import pipeline gate) ──

def review_queue(conn) -> list[dict]:
    """Real variants and why each is or is not publishable (brand, image, precise size/model, category)."""
    out = []
    for r in conn.execute("""SELECT m.id, m.canonical_name_fa, m.brand, m.category, m.image_urls_json, m.variant_label, m.status,
                                    p.id AS sku_id, p.slug, p.is_active
                             FROM master_products m LEFT JOIN products p ON p.master_product_id=m.id
                             WHERE m.provenance='real' ORDER BY p.is_active, m.id"""):
        problems = []
        if not (r["brand"] or "").strip():
            problems.append("برند ندارد")
        try:
            images = json.loads(r["image_urls_json"] or "[]")
        except (ValueError, TypeError):
            images = None
        if not isinstance(images, list) or not any(isinstance(image, str) and image.strip() for image in images):
            problems.append("تصویر معتبر ندارد")
        if r["status"] == "merged":
            problems.append("مرجع ادغام‌شده قابل انتشار نیست")
        if not r["variant_label"]:
            problems.append("اندازه/مدل مشخص نیست")
        if not r["sku_id"] and not conn.execute("SELECT 1 FROM categories WHERE slug=? AND level='category'", (r["category"],)).fetchone():
            problems.append("دسته نامعتبر")
        out.append({"master_product_id": r["id"], "title_fa": r["canonical_name_fa"], "brand": r["brand"], "category": r["category"],
                    "slug": r["slug"], "visible": bool(r["is_active"]), "problems": problems,
                    "publishable": not [p for p in problems if p != "اندازه/مدل مشخص نیست"]})
    return out


def set_visibility(conn, *, master_product_id: int, visible: bool, reason: str) -> dict:
    import datetime
    from app.core.errors import ConflictError, NotFoundError, ValidationError
    if type(visible) is not bool:
        raise ValidationError("visible باید مقدار بولی صریح باشد")
    if not isinstance(reason, str) or len(reason.strip()) < 3:
        raise ValidationError("دلیل انتشار/توقف الزامی است")
    row = next((r for r in review_queue(conn) if r["master_product_id"] == master_product_id), None)
    if row is None:
        raise NotFoundError("کالای واقعی یافت نشد")
    if visible and conn.execute("SELECT status FROM master_products WHERE id=?",(master_product_id,)).fetchone()[0]!="active":
        raise ConflictError("کالای غیرفعال قابل انتشار نیست",code="product_channel_unavailable")
    if visible and not row["publishable"]:
        raise ConflictError("کالا شرایط انتشار را ندارد: " + "، ".join(row["problems"]), code="not_publishable")
    m = conn.execute("SELECT * FROM master_products WHERE id=?", (master_product_id,)).fetchone()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pub = conn.execute("SELECT slug FROM catalog_publications WHERE master_product_id=?", (master_product_id,)).fetchone()
    if pub:
        conn.execute("UPDATE catalog_publications SET is_visible=?, publication_reason=?, updated_at=? WHERE master_product_id=?",
                     (1 if visible else 0, reason.strip(), now, master_product_id))
    else:
        conn.execute("""INSERT INTO catalog_publications (master_product_id, slug, category_slug, currency, is_visible, is_purchasable,
                        price_status, publication_reason, created_at, updated_at) VALUES (?,?,?,'IRR',?,0,'pending',?,?,?)""",
                     (master_product_id, row["slug"] or f"p-{m['public_product_id']}", m["category"], 1 if visible else 0, reason.strip(), now, now))
    conn.execute("UPDATE products SET is_active=? WHERE master_product_id=?", (1 if visible else 0, master_product_id))
    conn.execute("UPDATE master_products SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (master_product_id,))
    return next(r for r in review_queue(conn) if r["master_product_id"] == master_product_id)


def reconcile_family_groups(conn, group_keys) -> dict:
    """Reconcile selected current groups only; caller bootstraps keys BEFORE identity changes.

    Existing SKU identity/publication sync belongs to the identity transaction.
    This function never creates SKUs or changes unselected family/master records.
    """
    from app.core.errors import ValidationError
    if not isinstance(group_keys, (set, frozenset)) or not all(isinstance(k, str) and k for k in group_keys):
        raise ValidationError("گروه‌های هدف نامعتبر است")
    return apply(conn, create_skus=False, group_keys=frozenset(group_keys))
