#!/usr/bin/env python3
"""چک‌لیست خودکار پیش از راه‌اندازی (روز صفر). Read-only: changes nothing.

Usage (on the server, with the production environment loaded):
    python -m scripts.launch_preflight          # table; exit 1 if any BLOCKER
    python -m scripts.launch_preflight --json

Levels: BLOCKER = do not open the site; WARN = open only knowingly; OK / INFO.
Run it again after every fix and once more right before switching DNS.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BLOCKER, WARN, OK, INFO = "BLOCKER", "WARN", "OK", "INFO"
MIN_PRODUCTS = 50          # a storefront with fewer buyable items looks empty on day one
REQUIRED_DOCS = ("buyer_terms", "seller_terms", "privacy")
SEED_PASSWORDS = {          # scripts/seed.py demo accounts — must not survive into production
    "demo@70online.ir": "Demo!2345", "admin@70online.ir": "Admin!2345", "hr@parsco.ir": "Hr!23456789",
    "alice@parsco.ir": "Alice!23456", "bob@parsco.ir": "Bob!23456789",
}


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _writable(path: str | None) -> bool:
    if not path or not os.path.isdir(path):
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=path):
            return True
    except OSError:
        return False


def config_checks() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    add = lambda level, key, msg: out.append((level, key, msg))  # noqa: E731
    env = os.environ.get("APP_ENV", "development")
    add(OK if env == "production" else BLOCKER, "APP_ENV", f"محیط: {env} (باید production باشد)")
    add(BLOCKER if _on("DEMO_MODE") else OK, "DEMO_MODE", "حالت نمایشی باید خاموش باشد")
    for flag in ("COMMERCE_TEST_MODE", "TEST_SALES_OVERRIDE", "SEED_ON_START"):
        add(BLOCKER if _on(flag) else OK, flag, "باید خاموش باشد (کالای تست/دادهٔ نمونه نباید فروخته شود)")
    base = os.environ.get("PUBLIC_BASE_URL", "")
    add(OK if base.startswith("https://") else BLOCKER, "PUBLIC_BASE_URL", f"آدرس عمومی با https: «{base or 'خالی'}»")
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    bad = [o for o in origins if not o.startswith("https://") or "localhost" in o]
    add(BLOCKER if (not origins or bad) else OK, "CORS_ORIGINS", f"فقط دامنه‌های https سایت؛ مشکل‌دار: {bad or ('خالی' if not origins else '—')}")
    secret = os.environ.get("SECRET_KEY", "")
    add(OK if len(secret) >= 32 else BLOCKER, "SECRET_KEY", "کلید تصادفی دست‌کم ۳۲ نویسه (openssl rand -hex 32)")
    pay = os.environ.get("PAYMENT_PROVIDER", "mock")
    add(OK if pay == "sepehr" and os.environ.get("SEPEHR_TERMINAL_ID") else BLOCKER, "PAYMENT_PROVIDER",
        f"درگاه واقعی سپهر با شمارهٔ ترمینال (الان: {pay})")
    add(OK if _on("STOREFRONT_SALES_ENABLED") else WARN, "STOREFRONT_SALES_ENABLED", "خاموش = سایت فقط ویترین است و خرید ممکن نیست")
    add(OK if _on("LEGAL_REQUIRE_BUYER_TERMS") else BLOCKER, "LEGAL_REQUIRE_BUYER_TERMS", "پذیرش شرایط خرید باید در پرداخت ثبت شود")
    sms_ok = os.environ.get("SMS_PROVIDER") == "kavenegar" and os.environ.get("KAVENEGAR_API_KEY") and os.environ.get("KAVENEGAR_TEMPLATE")
    add(OK if sms_ok else WARN, "SMS_PROVIDER", "ورود پیامکی بدون کاوه‌نگار کار نمی‌کند")
    for f in ("FEATURE_INSTALLMENTS", "FEATURE_DEBT_SALE", "FEATURE_SELLER_ADVANCES"):
        add(WARN if _on(f) else OK, f, "اعتبار/اقساط فقط با مجوز و قرارداد نهاد مالی روشن شود")
    try:
        rl = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "0"))
    except ValueError:
        rl = 0
    add(OK if rl > 0 else WARN, "RATE_LIMIT_PER_MINUTE", "محدودیت درخواست برای جلوگیری از سوءاستفاده")
    add(OK if _writable(os.environ.get("MEDIA_ROOT")) else BLOCKER, "MEDIA_ROOT", "پوشهٔ پایدار و قابل‌نوشتن برای تصاویر")
    add(OK if _writable(os.environ.get("DOCUMENT_STORAGE_DIR")) else WARN, "DOCUMENT_STORAGE_DIR", "پوشهٔ مدارک فروشندگان/برندها")
    add(WARN if os.environ.get("EXTERNAL_CHANNELS_ENABLED") == "1" else OK, "EXTERNAL_CHANNELS_ENABLED",
        "اکوسیستم بسته: فید ترب و خروجی باسلام خاموش بماند مگر با تصمیم آگاهانه")
    vis = os.environ.get("STOREFRONT_PRICE_VISIBILITY", "public")
    add(OK if vis == "organizations" else WARN, "STOREFRONT_PRICE_VISIBILITY",
        f"شروع سازمانی: قیمت فقط برای اعضای سازمان‌ها، فروشندگان و مدیران (الان: {vis})")
    hops = os.environ.get("TRUSTED_PROXY_HOPS", "")
    add(OK if hops.isdigit() and int(hops) >= 1 else WARN, "TRUSTED_PROXY_HOPS",
        "پشت nginx/Cloudflare باید تعداد پراکسی‌های مورد اعتماد تنظیم شود؛ وگرنه محدودیت نرخ همه را یک IP می‌بیند")
    cap = os.environ.get("OTP_DAILY_SMS_CAP", "")
    add(OK if cap.isdigit() else INFO, "OTP_DAILY_SMS_CAP", f"سقف روزانهٔ پیامک کد ورود (پیش‌فرض ۳۰۰۰؛ الان: {cap or 'پیش‌فرض'})")
    return out


def db_checks(db) -> list[tuple[str, str, str]]:
    from app.core.migrator import _migrations_dir, applied_versions, discover
    from app.core.security import verify_password
    from app.services import consumer_rights_service as crs

    out: list[tuple[str, str, str]] = []
    add = lambda level, key, msg: out.append((level, key, msg))  # noqa: E731
    done = applied_versions(db)
    pending = [v for v, _, _ in discover(directory=_migrations_dir(db)) if v not in done]
    add(BLOCKER if pending else OK, "migrations", f"مهاجرت‌های اجرانشده: {pending or '—'} (python -m scripts.migrate)")
    with db.read_transaction() as conn:
        q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        live_seed = []
        for email, pw in SEED_PASSWORDS.items():
            r = conn.execute("SELECT password_hash, is_active FROM users WHERE email_normalized=?", (email,)).fetchone()
            if r and r["is_active"] and verify_password(pw, r["password_hash"]):
                live_seed.append(email)
        add(BLOCKER if live_seed else OK, "seed_accounts", f"حساب‌های نمونه با رمز شناخته‌شده: {live_seed or '—'}")
        admins = q("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1")
        add(OK if admins else BLOCKER, "admin", f"مدیر فعال: {admins}")
        zero = "0" * 64
        missing = [d for d in REQUIRED_DOCS
                   if not q("SELECT COUNT(*) FROM legal_documents WHERE doc_key=? AND text_sha256<>?", d, zero)]
        add(BLOCKER if missing else OK, "legal_documents", f"متن نهایی (تأیید وکیل) منتشر نشده: {missing or '—'}")
        vat = crs.standard_vat_bps(conn)
        add(OK if vat > 0 else BLOCKER, "vat", f"نرخ مالیات بر ارزش افزوده: {vat / 100:g}٪")
        sellers = q("SELECT COUNT(*) FROM suppliers WHERE status='active' AND provenance='real'")
        add(OK if sellers else BLOCKER, "sellers", f"فروشندهٔ واقعی فعال: {sellers}")
        held = q("SELECT COUNT(*) FROM suppliers WHERE status='active' AND payout_hold=1")
        add(INFO, "payout_hold", f"فروشنده‌های منتظر تأیید شبا: {held}")
        live = q("""SELECT COUNT(DISTINCT so.product_id) FROM seller_offers so JOIN suppliers s ON s.id=so.supplier_id
                    WHERE so.status='active' AND s.status='active' AND so.provenance='real' AND s.provenance='real'
                      AND so.selling_price_minor>0 AND so.stock_quantity>so.stock_reserved""")
        add(OK if live >= MIN_PRODUCTS else WARN, "catalog", f"کالای واقعی قیمت‌دار و موجود: {live} (هدف روز اول ≥ {MIN_PRODUCTS})")
        stale = q("SELECT COUNT(*) FROM carrier_tariffs WHERE is_active=1 AND updated_at=created_at")
        add(WARN if stale else OK, "tariffs", f"تعرفهٔ حمل نمونه که هنوز با قرارداد واقعی به‌روز نشده: {stale}")
        orgs = q("SELECT COUNT(*) FROM organizations")
        add(OK if orgs else WARN, "organizations", f"سازمان‌های ثبت‌شده (مشتری اول): {orgs}")
        contracts = q("SELECT COUNT(*) FROM credit_contracts")
        add(INFO, "credit_contracts", f"قرارداد اعتباری ثبت‌شده: {contracts} — پیش از فعال‌کردن خرید اعتباری، مجوز آن را با وکیل تأیید کنید")
        new_apps = q("SELECT COUNT(*) FROM b2b_applications WHERE status='new'")
        add(INFO, "b2b_applications", f"درخواست حساب سازمانی بی‌پاسخ: {new_apps}")
        unverified = q("SELECT COUNT(*) FROM affiliates WHERE sheba IS NOT NULL AND sheba_verified_at IS NULL AND status='active'")
        add(WARN if unverified else OK, "affiliate_sheba", f"شبای همکار فروش منتظر استعلام بانکی و تأیید: {unverified}")
    return out


def main(argv: list[str]) -> int:
    rows = config_checks()
    try:
        from app.core.config import load_settings
        from app.core.db import make_backend
        rows += db_checks(make_backend(load_settings().database_url))
    except Exception as exc:  # noqa: BLE001 — report, never crash the checklist
        rows.append((BLOCKER, "database", f"اتصال/بررسی پایگاه‌داده ناموفق: {exc}"))
    blockers = sum(1 for r in rows if r[0] == BLOCKER)
    if "--json" in argv:
        print(json.dumps({"blockers": blockers, "checks": [dict(zip(("level", "key", "message"), r)) for r in rows]},
                         ensure_ascii=False, indent=2))
    else:
        order = {BLOCKER: 0, WARN: 1, INFO: 2, OK: 3}
        for level, key, msg in sorted(rows, key=lambda r: order[r[0]]):
            print(f"{level:8} {key:28} {msg}")
        print(f"\n{'❌ ' + str(blockers) + ' مانع راه‌اندازی' if blockers else '✅ مانعی نیست'}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
