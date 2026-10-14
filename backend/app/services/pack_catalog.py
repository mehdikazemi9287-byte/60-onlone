"""Editorial pack definitions built only from REAL catalog variants (matched by exact normalized name).

Items whose product is missing or not visible are skipped; a pack is published only if it keeps at
least three real items and passes the diversity gate. No prices or budgets are set here.
"""
from __future__ import annotations

from app.core.errors import ConflictError
from app.services import pack_service
from app.services import text_norm as tn

RICE_2ND = "برنج کشت دوم ایرانی طبیعت 4.5 کیلوگرم"
OIL_27, OIL_4, OIL_5 = ("روغن نیمه‌جامد زیروترانس پرسپولیس طبیعت 2.7 کیلوگرم", "روغن نیمه‌جامد زیروترانس پرسپولیس طبیعت 4 کیلوگرم",
                        "روغن نیمه‌جامد زیروترانس پرسپولیس طبیعت 5 کیلوگرم")
MILK, KEFIR, LABNEH = "شیر پرچرب فرادما کاله", "ماست چکیده کفیر پروبیوتیک ناری کاله", "پنیر لبنه آنا کاله"
TROUT_800, TROUT_1, SALMON_1 = "ماهی قزل‌آلا مهیا 800 گرمی", "ماهی قزل‌آلا مهیا 1 کیلویی", "ماهی آزاد شکم خالی تازه مهیا 1 کیلویی"
TEA_GIFT = "دمنوش کادویی ترمه تواضع"
PISTACHIO_SPREAD_S, PISTACHIO_SPREAD_L = "معجون پسته کوچک تواضع", "معجون پسته بزرگ تواضع"

# (slug, title, kind, tier, occasion, audience, household, purpose, packaging, substitution, customizable, sort, [(name, qty, required)])
PACKS = [
    ("livelihood-economy-2", "سبد معیشتی اقتصادی دو نفره", "livelihood", "economy", None, "household", 2,
     "اقلام پایه یک هفته برای خانوار دو نفره با کمترین تنوع", "کارتن", "same_type", 1, 10,
     [(RICE_2ND, 1, 1), (OIL_27, 1, 1), (MILK, 6, 1), (LABNEH, 1, 1), (TROUT_800, 1, 0)]),
    ("livelihood-standard-4", "سبد معیشتی استاندارد چهار نفره", "livelihood", "standard", None, "household", 4,
     "اقلام اصلی خانوار چهار نفره شامل برنج هاشمی، گوشت، ماهی و لبنیات", "کارتن", "same_type", 1, 20,
     [("برنج هاشمی ممتاز طبیعت 5 کیلوگرم", 1, 1), (OIL_4, 1, 1), ("ران گوساله مهیا 1 کیلویی", 1, 1), (TROUT_1, 1, 1),
      (MILK, 12, 1), (KEFIR, 2, 0), (LABNEH, 2, 1)]),
    ("livelihood-complete-5", "سبد معیشتی کامل پنج نفره", "livelihood", "complete", None, "household", 5,
     "سبد کامل ماهانه با گوشت قرمز، ماهی آزاد و قزل‌آلا و لبنیات کامل", "کارتن دوتایی", "same_type_and_size", 1, 30,
     [("برنج هاشمی ممتاز طبیعت 10 کیلوگرم", 1, 1), (OIL_5, 1, 1), ("ران گوساله مهیا 2 کیلویی", 1, 1), ("ران گوسفند مهیا 1 کیلویی", 1, 1),
      (SALMON_1, 1, 1), (TROUT_1, 1, 0), (MILK, 20, 1), (KEFIR, 3, 1), (LABNEH, 3, 1)]),
    ("ramadan", "سبد ماه رمضان", "occasion", "standard", "رمضان", "household", 4,
     "سحری و افطار: خرما، دمنوش، برنج عنبربو و لبنیات", "جعبه", "same_type", 1, 40,
     [("کادویی سبد خرما مغزدار تواضع", 1, 1), (TEA_GIFT, 1, 1), ("برنج عنبربو طبیعت 5 کیلوگرم", 1, 1), (LABNEH, 2, 1), (MILK, 6, 0)]),
    ("nowruz", "پک نوروز", "occasion", "premium", "نوروز", "household", None,
     "پذیرایی ایام نوروز با آجیل مجلسی و پسته", "جعبه هدیه", "same_type", 1, 50,
     [("آجیل مجلسی تواضع", 1, 1), ("پسته احمدآقایی شور تواضع", 1, 1), ("کادویی سبد شماره 1 تواضع", 1, 1), (PISTACHIO_SPREAD_L, 1, 0)]),
    ("yalda", "پک شب یلدا", "occasion", "standard", "یلدا", "household", None,
     "آجیل و پسته مخصوص شب یلدا", "جعبه", "same_type", 1, 60,
     [("آجیل شب یلدا و چهارشنبه‌سوری تواضع", 1, 1), ("آجیل مشکل‌گشا تواضع", 1, 1), ("پسته شامی با پوست شور تواضع", 1, 1), (TEA_GIFT, 1, 0)]),
    ("org-hospitality", "پک پذیرایی سازمانی", "organizational", "standard", None, "organization", None,
     "پذیرایی جلسات و مهمانان سازمان", "کارتن سازمانی", "same_type", 1, 70,
     [("آجیل مخصوص سلامت تواضع", 2, 1), ("نخودچی شور تواضع", 1, 1), (TEA_GIFT, 2, 1), (MILK, 24, 0)]),
    ("office-desk", "پک تجهیزات میز کار", "organizational", "standard", None, "office", None,
     "تجهیز میز کار کارمند جدید: نمایشگر، هدفون و پاوربانک", "بسته‌بندی جداگانه اقلام", "ask", 1, 80,
     [("مانیتور ایسوس مدل VY229HE سایز 22 اینچ", 1, 1), ("هدفون بی‌سیم لنوو مدل HD200", 1, 1),
      ("پاوربانک پاورولوجی مدل PPBCHA05 ظرفیت 20000 میلی‌آمپر", 1, 1)]),
    ("employee-gift", "هدیه کارکنان", "organizational", "premium", "هدیه پایان سال", "employee_gift", None,
     "هدیه مناسبتی برای کارکنان با بسته‌بندی کادویی", "جعبه کادویی", "same_type", 1, 90,
     [("کادویی سبد شماره 33 تواضع", 1, 1), (PISTACHIO_SPREAD_S, 1, 1), (TEA_GIFT, 1, 1)]),
    ("family-protein", "پک پروتئین خانواده", "theme", "premium", None, "household", 4,
     "گوشت قرمز و ماهی برای یک ماه خانوار", "یخچالی", "same_type_and_size", 1, 100,
     [("ران گوسفند مهیا 2 کیلویی", 1, 1), ("سردست گوساله مهیا", 1, 1), (SALMON_1, 1, 1), ("راسته گوساله مهیا", 1, 1), ("ماهیچه گوسفند مهیا", 1, 0)]),
    ("breakfast", "پک صبحانه", "theme", "standard", None, "household", 3,
     "اقلام صبحانه: پنیر لبنه، ماست، شیر و معجون پسته", "کارتن", "same_type", 1, 110,
     [(LABNEH, 1, 1), (KEFIR, 1, 1), (MILK, 4, 1), (PISTACHIO_SPREAD_S, 1, 0)]),
    ("labor-day", "هدیه روز کارگر", "occasion", "standard", "روز کارگر", "employee_gift", None,
     "قدردانی از کارکنان در روز کارگر با خشکبار و سبد کادویی", "جعبه کادویی", "same_type", 1, 95,
     [("کادویی سبد شماره 11 تواضع", 1, 1), ("آجیل چهار مغز خام تواضع", 1, 1), ("پسته احمدآقایی خام تواضع", 1, 1), ("تخمه کدو گوشتی قره‌قروتی تواضع", 1, 0)]),
    ("catering-bulk", "پک عمده آشپزخانه و کترینگ", "organizational", "economy", None, "organization", None,
     "تأمین عمده برنج و روغن برای آشپزخانه سازمان، رستوران یا کترینگ", "بسته‌بندی عمده", "same_type_and_size", 1, 115,
     [("برنج پاکستانی طبیعت 4.5 کیلوگرمی", 4, 1), ("برنج کشت دوم ایرانی طبیعت 10 کیلوگرم", 2, 1), ("روغن سرخ‌کردنی خانواده طبیعت 16 کیلوگرمی", 1, 1),
      ("روغن سویا تصفیه‌شده خانواده طبیعت 16 کیلوگرمی", 1, 0), ("گردن گوساله مهیا", 2, 0)]),
    ("custom-org", "پک سفارشی سازمانی", "custom", None, None, "organization", None,
     "نقطه شروع برای ساخت پک اختصاصی سازمان؛ همه اقلام قابل تغییر است", "به انتخاب سازمان", "ask", 1, 120,
     [("برنج هاشمی ممتاز طبیعت 4.5 کیلوگرم", 1, 1), (OIL_27, 1, 1), ("آجیل رویال تواضع", 1, 1)]),
    # Figma 166:218 library additions — still only exact real catalog names.
    ("family-daily", "پک روزمره خانواده", "livelihood", "standard", None, "household", 3,
     "اقلام اصلی خانه: برنج هاشمی، روغن و لبنیات کاله", "کارتن", "same_type", 1, 5,
     [("برنج هاشمی ممتاز طبیعت 2.5 کیلوگرم", 1, 1), (OIL_27, 1, 1), (MILK, 4, 1), (LABNEH, 1, 0), (KEFIR, 1, 0)]),
    ("economy-small", "پک اقتصادی کوچک", "livelihood", "economy", None, "household", 1,
     "اقلام پایه برای یک نفر با بودجه کمتر", "کارتن", "same_type", 1, 12,
     [("برنج هاشمی ممتاز طبیعت 900 گرم", 2, 1), (OIL_27, 1, 1), (MILK, 3, 1), (KEFIR, 1, 0)]),
    ("premium-family", "پک ممتاز خانواده", "livelihood", "premium", None, "household", 4,
     "برنج عنبربو، گوشت گوسفندی بدون استخوان، ماهی آزاد و لبنیات", "کارتن دوتایی", "same_type_and_size", 1, 35,
     [("برنج عنبربو طبیعت 10 کیلوگرم", 1, 1), (OIL_5, 1, 1), ("راسته بدون استخوان گوسفند مهیا", 1, 1),
      ("ماهی آزاد شکم خالی تازه مهیا 1800 گرمی", 1, 1), (KEFIR, 2, 1), (LABNEH, 2, 0), ("آجیل رویال تواضع", 1, 0)]),
    ("gathering-tea", "پک دورهمی و دمنوش", "theme", "standard", None, "household", None,
     "پذیرایی دورهمی با دمنوش، چهار مغز و خرما مغزدار", "جعبه", "same_type", 1, 65,
     [(TEA_GIFT, 1, 1), ("آجیل چهار مغز خام تواضع", 1, 1), ("کادویی سبد خرما مغزدار تواضع", 1, 1)]),
    ("party", "پک جشن و مهمانی", "occasion", "standard", "جشن", "household", None,
     "پذیرایی جشن و تولد: بستنی، آجیل شیرین و آجیل مجلسی", "کارتن یخچالی", "same_type", 1, 66,
     [("بستنی ژلاتو آلو کاله", 2, 1), ("آجیل شیرین کلاسیک تواضع", 1, 1), ("آجیل مجلسی تواضع", 1, 1), ("نخودچی شور تواضع", 1, 0)]),
    ("nuts-health", "پک آجیل سلامت", "theme", "standard", None, "household", None,
     "مغزهای خام و آجیل سلامت برای میان‌وعده", "جعبه", "same_type", 1, 105,
     [("آجیل مخصوص سلامت تواضع", 1, 1), ("آجیل چهار مغز خام تواضع", 1, 1), ("پسته احمدآقایی خام تواضع", 1, 1), ("آجیل سبزمز تواضع", 1, 0)]),
    ("bbq", "پک کباب و مهمانی", "theme", "standard", None, "household", 6,
     "گوشت کبابی گوساله و گوسفند با برنج عنبربو و ماست", "یخچالی", "same_type_and_size", 1, 102,
     [("راسته گوساله مهیا", 1, 1), ("ران گوسفند مهیا 1 کیلویی", 1, 1), ("قلوه‌گاه گوسفند مهیا", 1, 1),
      ("برنج عنبربو طبیعت 5 کیلوگرم", 1, 1), (KEFIR, 2, 0)]),
    ("seafood", "پک غذای دریایی", "theme", "premium", None, "household", 4,
     "ماهی آزاد و قزل‌آلای تازه همراه برنج هاشمی", "یخچالی", "same_type_and_size", 1, 103,
     [("ماهی آزاد شکم خالی بدون سر و دم مهیا", 1, 1), (TROUT_1, 1, 1), ("ماهی آزاد شکم خالی تازه مهیا 1 کیلویی", 1, 1),
      ("برنج هاشمی ممتاز طبیعت 2.5 کیلوگرم", 1, 0)]),
    ("new-home", "پک لوازم خانه نو", "theme", "complete", None, "household", None,
     "لوازم اصلی خانه: یخچال فریزر، لباسشویی، تلویزیون، جارو برقی و کتری", "بسته‌بندی جداگانه اقلام", "ask", 1, 108,
     [("یخچال فریزر پایین ظرفیت 367 لیتر اسنوا", 1, 1), ("ماشین لباسشویی 9 کیلویی آناهید اسنوا", 1, 1),
      ("تلویزیون هوشمند Ultra HD اسنوا 55 اینچ", 1, 1), ("جارو برقی Clean Art اسنوا", 1, 0), ("کتری برقی آردزیا مدل AKT-P1650ST", 1, 0)]),
    ("study-remote", "پک دانشجویی و دورکاری", "theme", "standard", None, "office", None,
     "لپ‌تاپ، هدفون بی‌سیم و پاوربانک برای کار و مطالعه بیرون از دفتر", "بسته‌بندی جداگانه اقلام", "ask", 1, 109,
     [("لپ تاپ اچ پی 15.6 اینچی مدل HP 250 G7 N4020 4GB 1TB HDD", 1, 1), ("هدفون بی‌سیم لنوو مدل HD200", 1, 1),
      ("پاوربانک پاورولوجی مدل PPBCHA05 ظرفیت 20000 میلی‌آمپر", 1, 0)]),
    ("small-office", "پک تجهیز دفتر کوچک", "organizational", "standard", None, "office", None,
     "روتر میکروتیک، لپ‌تاپ و نمایشگر برای راه‌اندازی دفتر کوچک", "بسته‌بندی جداگانه اقلام", "ask", 1, 82,
     [("MikroTik hEX S", 1, 1), ("لپ تاپ اچ پی 15.6 اینچی مدل HP 250 G7 N4020 4GB 1TB HDD", 1, 1), ("مانیتور ایسوس مدل VY229HE سایز 22 اینچ", 1, 1)]),
    ("digital-gift", "هدیه دیجیتال کارکنان", "organizational", "executive", "هدیه پایان سال", "employee_gift", None,
     "تبلت سامسونگ، هدفون بی‌سیم و پاوربانک برای هدیه کارکنان", "جعبه کادویی", "ask", 1, 92,
     [("Samsung Galaxy Tab A9", 1, 1), ("هدفون بی‌سیم لنوو مدل HD200", 1, 1), ("پاوربانک پاورولوجی مدل PPBCHA05 ظرفیت 20000 میلی‌آمپر", 1, 1)]),
    ("executive-gift", "هدیه مدیران", "organizational", "executive", "هدیه پایان سال", "employee_gift", None,
     "آجیل رویال، آجیل شور ممتاز، معجون پسته و دمنوش در بسته‌بندی کادویی", "جعبه کادویی", "same_type", 1, 93,
     [("آجیل رویال تواضع", 1, 1), ("آجیل شور ممتاز تواضع", 1, 1), (PISTACHIO_SPREAD_L, 1, 1), (TEA_GIFT, 1, 0)]),
]

def apply(conn) -> dict:
    names = {tn.normalize(r["canonical_name_fa"]): r["id"] for r in conn.execute(
        """SELECT m.id, m.canonical_name_fa FROM master_products m JOIN products p ON p.master_product_id=m.id
           WHERE m.provenance='real' AND p.is_active=1 AND p.provenance='real'""")}
    report = {"published": [], "skipped": [], "missing_items": []}
    for slug, title, kind, tier, occasion, audience, hh, purpose, packaging, subst, custom, sort, items in PACKS:
        resolved = []
        for name, qty, req in items:
            mid = names.get(tn.normalize(name))
            if mid:
                resolved.append((mid, qty, req))
            else:
                report["missing_items"].append(f"{slug}: {name}")
        row = conn.execute("SELECT id FROM packs WHERE slug=?", (slug,)).fetchone()
        values = (title, kind, tier, occasion, audience, purpose, hh, packaging, subst, custom, sort)
        if row:
            pack_id = row["id"]
            conn.execute("""UPDATE packs SET title_fa=?, kind=?, tier=?, occasion=?, audience=?, purpose_fa=?, household_size=?,
                            packaging_fa=?, substitution_policy=?, customizable=?, sort_order=?,
                            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""", (*values, pack_id))
            conn.execute("DELETE FROM pack_items WHERE pack_id=?", (pack_id,))
        else:
            pack_id = conn.execute("""INSERT INTO packs (title_fa, kind, tier, occasion, audience, purpose_fa, household_size,
                                      packaging_fa, substitution_policy, customizable, sort_order, slug, status, provenance)
                                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'draft','real')""", (*values, slug)).lastrowid
        for i, (mid, qty, req) in enumerate(resolved):
            conn.execute("INSERT INTO pack_items (pack_id, master_product_id, quantity, required, sort_order) VALUES (?,?,?,?,?)",
                         (pack_id, mid, qty, req, i))
        try:
            pack_service.quality_gate(conn, pack_id)
            conn.execute("UPDATE packs SET status='published' WHERE id=?", (pack_id,))
            report["published"].append(slug)
        except ConflictError as e:
            conn.execute("UPDATE packs SET status='draft' WHERE id=?", (pack_id,))
            report["skipped"].append(f"{slug}: {e.message}")
    return report
