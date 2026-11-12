# اصلاحات بازبینی ۱۲ نوامبر ۲۰۲۶ — شصت‌آنلاین

> قبل از کار روی هشدار قیمت/SSO/شبکه فروش/ونداپی این فایل را بخوانید تا کار تکراری انجام نشود.

- شاخه: `fix/review-2026-11-12` (از `main` @ `8f3bdac`) — merge به main، restart و deploy **نشده** (طبق AGENTS.md نیازمند تأیید صریح مالک).
- مناطق محافظت‌شده (`frontend/src/app/page.tsx` صفحه اصلی و `PackBuilder`) و هدر/فوتر فیگمای main **دست نخورده‌اند** (بررسی با `git diff --name-only origin/main`).

## SO-1 — Manifest نسخه واحد

| قابلیت | شاخه منبع | SHA | وضعیت در این شاخه |
|---|---|---|---|
| هدر/فوتر فیگما + پک‌ساز مصوب | `main` | `8f3bdac` | پایه |
| اصلاحات ممیزی + هشدار قیمت + شبکه فروش + SSO (شامل `marketplace-roadmap`) | `fix/audit-2026-11-10` | `573c687` | merge بدون تعارض |
| سرعت کاتالوگ/اسکلت/کنترل درخواست | `perf/catalog-and-loading-20261110` | `cfc89ba` | merge بدون تعارض |
| اتصال ونداپی (خاموش پیش‌فرض) | `feat/vandapay-gateway` | `4a1c644` | merge بدون تعارض |
| صف بررسی استرداد ونداپی (SO-4) | همین شاخه | — | تازه |

Migrationها پس از ادغام: `0079`–`0083` (از fix) و `0084` (تازه)، هر دو نسخه SQLite و PostgreSQL، بدون شماره تکراری.

## انجام‌شده

| کد | اصلاح | فایل‌ها |
|---|---|---|
| SO-1 | یک شاخه واحد طبق جدول بالا | — |
| SO-2 | سرویس هشدار با چرخه canceled/reserved/sending/unknown و `recover_stuck` + migration 0083 همراه منتقل شد (نه فقط UI) | `backend/app/services/price_alert_service.py`، `backend/migrations*/0083_*` |
| SO-3 | متن اعتماد قیمت از قرارداد وضعیت (`priceTrustText`) | `frontend/src/app/products/[id]/price-trust.ts`، `ProductDetail.tsx` |
| SO-4 | رویداد `refund.*` ونداپی اکنون یک ردیف پیگیری در `external_refund_reviews` باز می‌کند (یکتا به‌ازای رویداد، مسئول `finance`، مهلت ۲۴ ساعت)؛ سفارش و موجودی خودکار تغییر نمی‌کنند. آزمون تازه در `tests/test_vandapay.py`. | `backend/app/services/vandapay_webhook_service.py`، `backend/migrations/0084_external_refund_reviews.sql`، `backend/migrations_postgresql/0084_external_refund_reviews.sql` |

آزمون (SQLite): `test_price_alert_sms_lifecycle`، `test_price_alerts`، `test_retail_network`، `test_sso`، `test_vandapay`، `test_checkout`، `test_catalog_performance`، `test_catalog_api`، parity مهاجرت PG → همه سبز (۱۵۴ + ۲). یک آزمون مهاجرت 0083 که فرض «آخرین migration» داشت اصلاح شد. **کل suite بیش از ۲۸ دقیقه طول کشید و تا پایان اجرا نشد**؛ `next build` و آزمون PostgreSQL واقعی اجرا نشد.

## مانده

- SO-4 کامل: چرخه جبران فروشگاه (تطبیق مبلغ/منبع، استرداد جزئی/کامل، وب‌هوک خارج از ترتیب) + صفحه مدیر برای صف `external_refund_reviews`.
- SO-5: worker/cron هشدار، خط پیامک، ترمینال آزمایشی ونداپی، آزمون PostgreSQL سرویس هشدار و Docker build؛ گزارش آخرین اجرای موفق.
- اجرای کامل suite و `next build`، سپس استقرار با تأیید مالک.
