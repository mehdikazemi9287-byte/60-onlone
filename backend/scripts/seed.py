#!/usr/bin/env python3
"""Seed demo data. Idempotent: safe to run repeatedly.

Prices are given in Iranian Rial as exact integers (no floats anywhere).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.core.db import Database, make_backend  # noqa: E402
from app.core.migrator import upgrade  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.services import ledger_service  # noqa: E402

CATEGORIES = [
    ("laptop", "لپ‌تاپ و رایانه", 1),
    ("mobile", "موبایل و تبلت", 2),
    ("office", "لوازم اداری", 3),
    ("network", "تجهیزات شبکه", 4),
    ("appliance", "لوازم برقی", 5),
]

# (slug, sku, title, brand, category, price_irr, emoji, rating_x10, stock, description)
PRODUCTS = [
    ("laptop-asus-vivobook-15", "LP-ASUS-VB15", "لپ‌تاپ ایسوس VivoBook 15", "ایسوس", "laptop",
     289_000_000, "💻", 43, 12,
     "لپ‌تاپ ۱۵.۶ اینچی با پردازنده Core i5 نسل ۱۲، رم ۱۶ گیگابایت و حافظه SSD ۵۱۲ گیگابایت. مناسب کار اداری و دانشجویی."),
    ("laptop-lenovo-thinkpad-e14", "LP-LNV-E14", "لپ‌تاپ لنوو ThinkPad E14", "لنوو", "laptop",
     412_000_000, "💻", 46, 7,
     "لپ‌تاپ حرفه‌ای سازمانی با بدنه مقاوم، صفحه‌کلید استاندارد ThinkPad و گارانتی سازمانی سه ساله."),
    ("laptop-hp-probook-450", "LP-HP-PB450", "لپ‌تاپ اچ‌پی ProBook 450", "اچ‌پی", "laptop",
     368_500_000, "💻", 41, 4,
     "لپ‌تاپ اداری با پردازنده Core i7، مناسب استفاده طولانی‌مدت در محیط سازمانی."),
    ("mobile-samsung-a55", "MB-SAM-A55", "گوشی سامسونگ Galaxy A55", "سامسونگ", "mobile",
     198_000_000, "📱", 44, 25,
     "گوشی هوشمند با نمایشگر ۶.۶ اینچی Super AMOLED، دوربین ۵۰ مگاپیکسل و باتری ۵۰۰۰ میلی‌آمپرساعت."),
    ("mobile-xiaomi-redmi-note-13", "MB-XIA-RN13", "گوشی شیائومی Redmi Note 13", "شیائومی", "mobile",
     121_000_000, "📱", 42, 40,
     "گوشی اقتصادی با عملکرد مناسب، شارژ سریع ۳۳ وات و حافظه داخلی ۱۲۸ گیگابایت."),
    ("tablet-samsung-tab-a9", "MB-SAM-TA9", "تبلت سامسونگ Galaxy Tab A9", "سامسونگ", "mobile",
     94_500_000, "📱", 39, 15,
     "تبلت ۸.۷ اینچی سبک، مناسب مطالعه، جلسات آنلاین و استفاده روزمره."),
    ("office-chair-ergo-pro", "OF-CHR-EP1", "صندلی اداری ارگونومیک Ergo Pro", "نیلپر", "office",
     62_000_000, "🪑", 45, 30,
     "صندلی کارشناسی با پشتی مش، تنظیم ارتفاع گازی و زیر‌دستی قابل تنظیم."),
    ("office-desk-160", "OF-DSK-160", "میز کار اداری ۱۶۰ سانتی‌متر", "نیلپر", "office",
     78_000_000, "🗄️", 40, 18,
     "میز کار ملامینه با روکش مقاوم، دارای فایل کشویی و محل عبور کابل."),
    ("office-paper-a4-carton", "OF-PPR-A4C", "کاغذ A4 دبل‌ای (کارتن ۵ بسته)", "Double A", "office",
     14_500_000, "📄", 47, 120,
     "کارتن ۵ بسته‌ای کاغذ A4 هشتاد گرمی، مناسب مصرف اداری."),
    ("network-mikrotik-hex-s", "NT-MKT-HEXS", "روتر میکروتیک hEX S", "میکروتیک", "network",
     41_000_000, "🌐", 44, 22,
     "روتر پنج پورت گیگابیت با پورت SFP و پشتیبانی از RouterOS L4."),
    ("network-switch-24port", "NT-SWT-24G", "سوییچ ۲۴ پورت گیگابیت مدیریتی", "سیسکو", "network",
     156_000_000, "🌐", 43, 6,
     "سوییچ لایه ۲ مدیریتی، مناسب شبکه‌های سازمانی متوسط."),
    ("appliance-water-dispenser", "AP-WTR-D22", "آبسردکن ایستاده اداری", "پارس", "appliance",
     53_000_000, "🚰", 38, 9,
     "آبسردکن ایستاده با مخزن استیل، مناسب محیط‌های اداری تا ۳۰ نفر."),
    ("appliance-microwave-25l", "AP-MCW-25L", "مایکروویو ۲۵ لیتری", "ال‌جی", "appliance",
     67_500_000, "🍽️", 41, 11,
     "مایکروویو رومیزی ۲۵ لیتری با ۱۰ سطح توان و تایمر دیجیتال."),
    ("appliance-kettle-2l", "AP-KTL-2L0", "کتری برقی ۲ لیتری", "فیلیپس", "appliance",
     11_900_000, "☕", 40, 60,
     "کتری برقی استیل با خاموشی خودکار و فیلتر قابل شست‌وشو."),
]

USERS = [
    ("demo@70online.ir", "Demo!2345", "کاربر نمونه", "09120000000", "customer"),
    ("admin@70online.ir", "Admin!2345", "مدیر سامانه", "09121111111", "admin"),
    # --- Phase 2 demo organization ---
    ("hr@parsco.ir", "Hr!23456789", "سمیرا مرادی", "09122222222", "customer"),
    ("alice@parsco.ir", "Alice!23456", "الهام رضایی", "09123333333", "customer"),
    ("bob@parsco.ir", "Bob!23456789", "بهرام کریمی", "09124444444", "customer"),
]

# (national_id, legal_name, display_name, credit_limit_minor, billing_email)
DEMO_ORG = (
    "10101234567",
    "شرکت پارس فناوری نمونه (سهامی خاص)",
    "پارس فناوری",
    5_000_000_000,
    "finance@parsco.ir",
)

# (email, role, employee_code, department)
DEMO_MEMBERS = [
    ("hr@parsco.ir", "organization_admin", "P-001", "منابع انسانی"),
    ("alice@parsco.ir", "employee", "P-014", "طراحی"),
    ("bob@parsco.ir", "employee", "P-021", "فروش"),
]

# (email, allocated_minor, expires_at, category_slugs, per_transaction_limit_minor)
DEMO_ALLOCATIONS = [
    ("alice@parsco.ir", 200_000_000, None, None, None),
    ("bob@parsco.ir", 60_000_000, None, ["office", "appliance"], None),
]


def _seed_organization(conn) -> dict:
    """Idempotent demo organization: an org admin, two employees, two allocations."""
    from app.services import credit_service

    created = {"organizations": 0, "memberships": 0, "allocations": 0}
    national_id, legal_name, display_name, limit, billing = DEMO_ORG

    row = conn.execute(
        "SELECT id FROM organizations WHERE national_id = ?", (national_id,)
    ).fetchone()
    if row is None:
        admin = conn.execute(
            "SELECT id FROM users WHERE email_normalized = 'admin@70online.ir'"
        ).fetchone()
        cursor = conn.execute(
            """
            INSERT INTO organizations
                (legal_name, display_name, national_id, status, credit_policy,
                 credit_limit_minor, billing_email, created_by_user_id)
            VALUES (?,?,?, 'active', 'employer_funded', ?,?,?)
            """,
            (legal_name, display_name, national_id, limit, billing,
             int(admin["id"]) if admin else None),
        )
        org_id = int(cursor.lastrowid)
        created["organizations"] = 1
    else:
        org_id = int(row["id"])

    membership_ids = {}
    for email, role, code, department in DEMO_MEMBERS:
        user = conn.execute(
            "SELECT id FROM users WHERE email_normalized = ?", (email.lower(),)
        ).fetchone()
        if user is None:
            continue
        existing = conn.execute(
            "SELECT id FROM organization_memberships WHERE organization_id = ? AND user_id = ?",
            (org_id, int(user["id"])),
        ).fetchone()
        if existing is not None:
            membership_ids[email] = int(existing["id"])
            continue
        cursor = conn.execute(
            """
            INSERT INTO organization_memberships
                (organization_id, user_id, role, status, employee_code, department)
            VALUES (?,?,?, 'active', ?,?)
            """,
            (org_id, int(user["id"]), role, code, department),
        )
        membership_ids[email] = int(cursor.lastrowid)
        created["memberships"] += 1

    hr = conn.execute(
        "SELECT id FROM users WHERE email_normalized = 'hr@parsco.ir'"
    ).fetchone()
    if hr is not None:
        for email, amount, expires_at, categories, per_tx in DEMO_ALLOCATIONS:
            membership_id = membership_ids.get(email)
            if membership_id is None:
                continue
            already = conn.execute(
                "SELECT 1 FROM credit_allocations WHERE membership_id = ?", (membership_id,)
            ).fetchone()
            if already:
                continue
            user = conn.execute(
                "SELECT id FROM users WHERE email_normalized = ?", (email.lower(),)
            ).fetchone()
            reference = credit_service._ref("ALLOC")
            cursor = conn.execute(
                """
                INSERT INTO credit_allocations
                    (reference, organization_id, membership_id, user_id, allocated_minor,
                     currency, expires_at, category_slugs_json, per_transaction_limit_minor,
                     note, created_by_user_id)
                VALUES (?,?,?,?,?, 'IRR', ?,?,?,?,?)
                """,
                (reference, org_id, membership_id, int(user["id"]), amount, expires_at,
                 json.dumps(categories, ensure_ascii=False) if categories else None,
                 per_tx, "اعتبار نمونه دمو", int(hr["id"])),
            )
            allocation_id = int(cursor.lastrowid)
            allocation = conn.execute(
                "SELECT * FROM credit_allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
            credit_service._post_entry(
                conn, allocation=allocation, entry_type="allocation", amount_minor=amount,
                reference=reference, actor_user_id=int(hr["id"]), note="اعتبار نمونه دمو",
            )
            created["allocations"] += 1
    return created


# =====================================================================
# Phase 3: Demo Supplier Network
# =====================================================================

# Fulfillment policy assignments per product slug (None = default NATIONAL_SHIPPING)
PRODUCT_FULFILLMENT_POLICIES = {
    # Fresh/local products — LOCAL_ONLY
    # (none in current catalog; mapped conceptually to food-like slugs)
    # Mobile phones — LOCAL_PREFERRED
    "mobile-samsung-a55":           "LOCAL_PREFERRED",
    "mobile-xiaomi-redmi-note-13":  "LOCAL_PREFERRED",
    "tablet-samsung-tab-a9":        "LOCAL_PREFERRED",
    # Laptops — NATIONAL_SHIPPING
    "laptop-asus-vivobook-15":      "NATIONAL_SHIPPING",
    "laptop-lenovo-thinkpad-e14":   "NATIONAL_SHIPPING",
    "laptop-hp-probook-450":        "NATIONAL_SHIPPING",
    # Stationery/office — NATIONAL_SHIPPING
    "office-chair-ergo-pro":        "NATIONAL_SHIPPING",
    "office-desk-160":              "NATIONAL_SHIPPING",
    "office-paper-a4-carton":       "NATIONAL_SHIPPING",
    # Network — NATIONAL_SHIPPING
    "network-mikrotik-hex-s":       "NATIONAL_SHIPPING",
    "network-switch-24port":        "NATIONAL_SHIPPING",
    # Appliances — LOCAL_PREFERRED (heavy)
    "appliance-water-dispenser":    "LOCAL_PREFERRED",
    "appliance-microwave-25l":      "LOCAL_PREFERRED",
    "appliance-kettle-2l":          "NATIONAL_SHIPPING",
}

# Demo supplier users: (email, password, full_name, phone)
SUPPLIER_USERS = [
    ("supplier.tehran@70online.ir",     "Sup!Tehran1",  "مدیر تأمین‌کننده تهران",   "09130000001"),
    ("supplier.isfahan@70online.ir",    "Sup!Isfahan1", "مدیر تأمین‌کننده اصفهان",  "09130000002"),
    ("supplier.kermanshah@70online.ir", "Sup!Krmsh1",   "مدیر تأمین‌کننده کرمانشاه","09130000003"),
]

# Suppliers: (national_id, legal_name, display_name, type, status, rating_x10, user_email)
DEMO_SUPPLIERS = [
    # Tehran
    ("20101000001", "شرکت لوازم اداری البرز (سهامی خاص)",   "لوازم اداری البرز",   "retailer",   "active", 42, "supplier.tehran@70online.ir"),
    ("20101000002", "موبایل‌فروشی فناوران تهران",             "فناوران تهران",       "retailer",   "active", 45, "supplier.tehran@70online.ir"),
    ("20101000003", "سوپرمارکت تازه‌کالا تهران",             "تازه‌کالا تهران",     "local_shop", "active", 38, "supplier.tehran@70online.ir"),
    # Isfahan
    ("20101000004", "شرکت لوازم اداری سپاهان",               "لوازم اداری سپاهان",  "retailer",   "active", 40, "supplier.isfahan@70online.ir"),
    ("20101000005", "موبایل‌پلازا اصفهان",                   "موبایل‌پلازا اصفهان", "retailer",   "active", 43, "supplier.isfahan@70online.ir"),
    ("20101000006", "تازه‌بازار اصفهان (محلی)",              "تازه‌بازار اصفهان",   "local_shop", "active", 36, "supplier.isfahan@70online.ir"),
    # Kermanshah
    ("20101000007", "موبایل‌ورز کرمانشاه",                  "موبایل‌ورز کرمانشاه", "retailer",   "active", 41, "supplier.kermanshah@70online.ir"),
    ("20101000008", "کالای عمومی غرب",                       "کالای عمومی غرب",    "wholesaler", "active", 39, "supplier.kermanshah@70online.ir"),
    # Mazandaran (rice/citrus)
    ("20101000009", "تعاونی برنج شمال",                      "تعاونی برنج شمال",   "producer",   "active", 46, None),
    # Neyriz/Fars (pomegranate)
    ("20101000010", "باغداران انار نیریز",                   "انار نیریز",          "producer",   "active", 47, None),
    # Suspended (for security tests)
    ("20101000099", "تأمین‌کننده معلق",                      "تأمین‌کننده معلق",   "retailer", "suspended", 35, None),
]

# Locations: (supplier_national_id, province, city, local_del, intercity, pickup, prep_min)
DEMO_LOCATIONS = [
    # Tehran stationery
    ("20101000001", "تهران", "تهران", True,  True,  False, 120),
    # Tehran mobile
    ("20101000002", "تهران", "تهران", True,  True,  True,  60),
    # Tehran food/local
    ("20101000003", "تهران", "تهران", True,  False, False, 30),
    # Isfahan stationery
    ("20101000004", "اصفهان", "اصفهان", True,  True,  False, 120),
    # Isfahan mobile
    ("20101000005", "اصفهان", "اصفهان", True,  True,  True,  60),
    # Isfahan food/local
    ("20101000006", "اصفهان", "اصفهان", True,  False, False, 45),
    # Kermanshah mobile
    ("20101000007", "کرمانشاه", "کرمانشاه", True,  True,  True,  90),
    # Kermanshah general
    ("20101000008", "کرمانشاه", "کرمانشاه", True,  True,  False, 180),
    # Mazandaran (intercity only)
    ("20101000009", "مازندران", "ساری", False, True,  False, 240),
    # Neyriz (intercity only)
    ("20101000010", "فارس", "نیریز", False, True,  False, 300),
    # Suspended supplier location
    ("20101000099", "تهران", "تهران", True,  True,  False, 60),
]

# Offers: (supplier_national_id, product_slug, selling_price_minor, cost_price_minor, stock, fulfillment_type)
DEMO_OFFERS = [
    # Tehran stationery supplier — office products
    ("20101000001", "office-paper-a4-carton", 15_000_000,  11_000_000, 80, "delivery"),
    ("20101000001", "office-chair-ergo-pro",  64_000_000,  48_000_000, 15, "delivery"),
    ("20101000001", "office-desk-160",         80_000_000,  60_000_000, 8,  "delivery"),
    ("20101000001", "network-mikrotik-hex-s",  42_000_000,  32_000_000, 10, "delivery"),
    ("20101000001", "network-switch-24port",  158_000_000, 120_000_000, 3,  "delivery"),
    ("20101000001", "appliance-kettle-2l",     12_500_000,   9_000_000, 20, "delivery"),
    # Tehran mobile supplier
    ("20101000002", "mobile-samsung-a55",          200_000_000, 155_000_000, 15, "both"),
    ("20101000002", "mobile-xiaomi-redmi-note-13", 124_000_000,  95_000_000, 20, "both"),
    ("20101000002", "tablet-samsung-tab-a9",         97_000_000,  75_000_000, 10, "both"),
    ("20101000002", "laptop-asus-vivobook-15",       292_000_000, 225_000_000, 5,  "delivery"),
    ("20101000002", "laptop-lenovo-thinkpad-e14",    415_000_000, 320_000_000, 3,  "delivery"),
    # Tehran local food/general (LOCAL_ONLY appliances)
    ("20101000003", "appliance-water-dispenser",  55_000_000, 42_000_000, 6,  "delivery"),
    ("20101000003", "appliance-microwave-25l",    69_000_000, 53_000_000, 4,  "delivery"),
    ("20101000003", "appliance-kettle-2l",        12_900_000,  9_500_000, 30, "delivery"),
    # Isfahan stationery supplier
    ("20101000004", "office-paper-a4-carton", 14_800_000,  11_000_000, 60, "delivery"),
    ("20101000004", "office-chair-ergo-pro",  63_000_000,  47_000_000, 12, "delivery"),
    ("20101000004", "office-desk-160",         79_000_000,  59_000_000, 6,  "delivery"),
    ("20101000004", "appliance-kettle-2l",     12_200_000,   9_200_000, 25, "delivery"),
    # Isfahan mobile supplier
    ("20101000005", "mobile-samsung-a55",          199_000_000, 154_000_000, 8,  "both"),
    ("20101000005", "mobile-xiaomi-redmi-note-13", 122_000_000,  94_000_000, 15, "both"),
    ("20101000005", "tablet-samsung-tab-a9",         95_500_000,  73_000_000, 6,  "both"),
    ("20101000005", "laptop-hp-probook-450",        370_000_000, 285_000_000, 2,  "delivery"),
    # Isfahan local food/appliance (LOCAL stock = 0 for scenario C)
    ("20101000006", "appliance-water-dispenser",  54_000_000, 41_000_000, 0,  "delivery"),  # stock=0 for test
    ("20101000006", "appliance-microwave-25l",    68_000_000, 52_000_000, 3,  "delivery"),
    # Kermanshah mobile
    ("20101000007", "mobile-samsung-a55",          202_000_000, 157_000_000, 4,  "both"),
    ("20101000007", "mobile-xiaomi-redmi-note-13", 125_000_000,  97_000_000, 8,  "both"),
    ("20101000007", "tablet-samsung-tab-a9",         98_000_000,  76_000_000, 3,  "both"),
    # Kermanshah general
    ("20101000008", "office-paper-a4-carton", 15_500_000,  11_500_000, 40, "delivery"),
    ("20101000008", "appliance-kettle-2l",     13_000_000,   9_800_000, 15, "delivery"),
    ("20101000008", "appliance-water-dispenser",  57_000_000, 44_000_000, 4,  "delivery"),
    # Mazandaran (intercity only)
    ("20101000009", "office-paper-a4-carton", 13_500_000,  10_000_000, 200, "delivery"),
    ("20101000009", "appliance-kettle-2l",     11_500_000,   8_500_000, 50, "delivery"),
    # Neyriz (intercity only)
    ("20101000010", "appliance-kettle-2l",     11_000_000,   8_000_000, 30, "delivery"),
    # Suspended supplier (should never be selected)
    ("20101000099", "office-paper-a4-carton", 12_000_000, 9_000_000, 100, "delivery"),
]


def _seed_phase3(conn) -> dict:
    """Idempotent Phase 3 demo supplier network seed."""
    created = {
        "supplier_users": 0, "suppliers": 0, "locations": 0, "offers": 0,
        "policy_assignments": 0,
    }

    # --- Supplier portal users ---
    for email, password, full_name, phone in SUPPLIER_USERS:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email_normalized = ?", (email.lower(),)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (email, email_normalized, password_hash, full_name, phone, role) "
                "VALUES (?,?,?,?,?, 'supplier')",
                (email, email.lower(), hash_password(password), full_name, phone),
            )
            created["supplier_users"] += 1

    # --- Suppliers ---
    supplier_ids: dict[str, int] = {}
    for nat_id, legal, display, stype, status, rating, user_email in DEMO_SUPPLIERS:
        existing = conn.execute(
            "SELECT id FROM suppliers WHERE national_id = ?", (nat_id,)
        ).fetchone()
        if existing:
            supplier_ids[nat_id] = int(existing["id"])
            continue
        user_id = None
        if user_email:
            u = conn.execute(
                "SELECT id FROM users WHERE email_normalized = ?", (user_email.lower(),)
            ).fetchone()
            if u:
                user_id = int(u["id"])
        cursor = conn.execute(
            "INSERT INTO suppliers (legal_name, display_name, national_id, supplier_type, "
            "status, rating_x10, user_id) VALUES (?,?,?,?,?,?,?)",
            (legal, display, nat_id, stype, status, rating, user_id),
        )
        supplier_ids[nat_id] = int(cursor.lastrowid)
        created["suppliers"] += 1

    # --- Locations ---
    location_ids: dict[str, int] = {}  # nat_id -> location_id (first one)
    for nat_id, province, city, local_del, intercity, pickup, prep in DEMO_LOCATIONS:
        sup_id = supplier_ids.get(nat_id)
        if sup_id is None:
            continue
        existing = conn.execute(
            "SELECT id FROM supplier_locations WHERE supplier_id = ? AND province = ? AND city = ?",
            (sup_id, province, city),
        ).fetchone()
        if existing:
            location_ids[nat_id] = int(existing["id"])
            continue
        cursor = conn.execute(
            "INSERT INTO supplier_locations "
            "(supplier_id, province, city, status, can_local_delivery, can_intercity_shipping, "
            "can_pickup, prep_time_minutes) VALUES (?,?,?, 'active', ?,?,?,?)",
            (sup_id, province, city, int(local_del), int(intercity), int(pickup), prep),
        )
        location_ids[nat_id] = int(cursor.lastrowid)
        created["locations"] += 1

    # --- Offers ---
    for nat_id, product_slug, sell_price, cost_price, stock, ft in DEMO_OFFERS:
        sup_id = supplier_ids.get(nat_id)
        loc_id = location_ids.get(nat_id)
        if sup_id is None or loc_id is None:
            continue
        prod_row = conn.execute(
            "SELECT id FROM products WHERE slug = ?", (product_slug,)
        ).fetchone()
        if prod_row is None:
            continue
        prod_id = int(prod_row["id"])
        existing = conn.execute(
            "SELECT id FROM seller_offers WHERE product_id = ? AND supplier_id = ? AND supplier_location_id = ?",
            (prod_id, sup_id, loc_id),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO seller_offers "
            "(product_id, supplier_id, supplier_location_id, selling_price_minor, cost_price_minor, "
            "stock_quantity, status, fulfillment_type) VALUES (?,?,?,?,?,?, 'active', ?)",
            (prod_id, sup_id, loc_id, sell_price, cost_price, stock, ft),
        )
        created["offers"] += 1

    # --- Fulfillment policy assignments ---
    policy_map = {
        r["name"]: r["id"] for r in conn.execute(
            "SELECT id, name FROM fulfillment_policies"
        ).fetchall()
    }
    for slug, policy_name in PRODUCT_FULFILLMENT_POLICIES.items():
        policy_id = policy_map.get(policy_name)
        if policy_id is None:
            continue
        prod_row = conn.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
        if prod_row is None:
            continue
        conn.execute(
            "UPDATE products SET fulfillment_policy_id = ? WHERE id = ? AND fulfillment_policy_id IS NULL",
            (policy_id, int(prod_row["id"])),
        )
        created["policy_assignments"] += 1

    return created


def seed(db: Database) -> dict:
    upgrade(db)
    created = {"categories": 0, "products": 0, "users": 0}
    with db.write_transaction() as conn:
        ledger_service.ensure_accounts(conn)

        for slug, name_fa, order in CATEGORIES:
            cur = conn.execute(
                "INSERT OR IGNORE INTO categories (slug, name_fa, sort_order) VALUES (?,?,?)",
                (slug, name_fa, order),
            )
            created["categories"] += cur.rowcount

        cat_ids = {
            r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM categories").fetchall()
        }

        for (slug, sku, title, brand, cat, price, emoji, rating, stock, desc) in PRODUCTS:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO products
                    (slug, sku, title_fa, description_fa, brand_fa, category_id,
                     base_price_minor, image_emoji, rating_x10)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (slug, sku, title, desc, brand, cat_ids[cat], price, emoji, rating),
            )
            created["products"] += cur.rowcount
            pid = conn.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()["id"]
            conn.execute(
                "INSERT OR IGNORE INTO inventory (product_id, quantity_available) VALUES (?,?)",
                (pid, stock),
            )

        for email, password, full_name, phone, role in USERS:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE email_normalized = ?", (email.lower(),)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO users (email, email_normalized, password_hash, full_name, phone, role)
                VALUES (?,?,?,?,?,?)
                """,
                (email, email.lower(), hash_password(password), full_name, phone, role),
            )
            created["users"] += 1

        created.update(_seed_organization(conn))
        created.update(_seed_phase3(conn))
    return created


def main() -> int:
    settings = load_settings()
    db = make_backend(settings.database_url)
    created = seed(db)
    totals = {
        "categories": db.query_one("SELECT COUNT(*) n FROM categories")["n"],
        "products": db.query_one("SELECT COUNT(*) n FROM products")["n"],
        "inventory_rows": db.query_one("SELECT COUNT(*) n FROM inventory")["n"],
        "users": db.query_one("SELECT COUNT(*) n FROM users")["n"],
        "ledger_accounts": db.query_one("SELECT COUNT(*) n FROM ledger_accounts")["n"],
    }
    totals["organizations"] = db.query_one("SELECT COUNT(*) n FROM organizations")["n"]
    totals["memberships"] = db.query_one("SELECT COUNT(*) n FROM organization_memberships")["n"]
    totals["credit_allocations"] = db.query_one("SELECT COUNT(*) n FROM credit_allocations")["n"]
    print(f"inserted: {created}")
    print(f"totals:   {totals}")
    print()
    print("demo accounts")
    print("  retail customer   demo@70online.ir  / Demo!2345")
    print("  platform admin    admin@70online.ir / Admin!2345")
    print("  org admin         hr@parsco.ir      / Hr!23456789      (پارس فناوری)")
    print("  employee + credit alice@parsco.ir   / Alice!23456      (۲۰,۰۰۰,۰۰۰ تومان)")
    print("  employee category bob@parsco.ir     / Bob!23456789     (محدود به اداری/لوازم برقی)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
