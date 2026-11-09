# وامبی (Vambi)

موتور جستجو و مقایسهٔ قیمت **درون اکوسیستم** شصت آنلاین. فقط فروشنده‌های خود اکوسیستم را نشان می‌دهد و هیچ داده‌ای به بیرون (ترب، ایمالز، باسلام و…) نمی‌دهد.

- دامنه: `vambi.ir` (ثبت شده)
- گزارش پیشرفت: [PROGRESS.md](PROGRESS.md)
- طراحی لوگو در فیگما: https://www.figma.com/design/g9Ke9JAAWnreYWKCGWDMle

## وضعیت کنونی
| بخش | وضعیت |
| --- | --- |
| جستجو و مقایسهٔ فروشنده‌ها (نسخهٔ اول) | ساخته شد |
| لوگو و ظاهر جدا | ساخته شد |
| هشدار قیمت سطح‌بندی‌شده | ساخته شد و بازبینی شد؛ مانده: QA نهایی و استقرار |
| ورود مشترک با شصت آنلاین | ساخته شد (شاخهٔ `vambi-sso`)؛ مانده: بازبینی امنیتی، QA و استقرار |
| استقرار روی vambi.ir | مانده (با تأیید کارن) |

## فایل‌های وامبی در ریپو
همهٔ کد وامبی در همین ریپو است، چون حساب کاربری، کالاها، قیمت‌ها و فروشنده‌ها با شصت آنلاین مشترک‌اند. این فهرست مرز وامبی را مشخص می‌کند:

**بک‌اند**
- `backend/app/api/v1/vambi.py`: جستجو (`/api/v1/vambi/search`)
- `backend/app/api/v1/price_alerts.py` و `backend/app/services/price_alert_service.py`: هشدار قیمت
- `backend/scripts/run_price_alerts.py`: کار ساعتی هشدارها (در `scripts/scheduler.py`)
- `backend/migrations/0079_price_alerts.sql`، `0080_price_alerts_review.sql` (و نسخهٔ PostgreSQL در `migrations_postgresql/`)
- تست‌ها: `backend/tests/test_vambi.py`، `backend/tests/test_price_alerts.py`

**فرانت**
- `frontend/src/app/vambi/`: صفحه و قالب وامبی
- `frontend/src/components/vambi/`: `VambiSearch`، `VambiShell`
- `frontend/public/vambi/`: لوگو (`mark.svg`، `icon.svg`)
- `frontend/src/middleware.ts`: نمایش `/vambi` روی دامنهٔ vambi.ir (`VAMBI_HOSTS`)
- ورود مشترک: `frontend/src/lib/sso.ts`، صفحه‌های `app/sso/vambi/` (روی شصت آنلاین) و `app/sso/callback/` (روی وامبی)، `components/vambi/VambiLoginButton.tsx`؛ بک‌اند `backend/app/services/sso_service.py`، مایگریشن `0082_sso_codes.sql`، تست `backend/tests/test_sso.py`
- مشترک با شصت آنلاین: `components/price-watch/WatchButton.tsx`، `lib/priceWatch.ts`، صفحهٔ `app/me/price-alerts/`، کارت `components/seller/SellerPriceAlerts.tsx`

## تنظیمات (env)
| متغیر | کجا | توضیح |
| --- | --- | --- |
| `VAMBI_DOMAIN` | سرور | `vambi.ir` |
| `VAMBI_HOSTS` | فرانت | دامنه‌هایی که صفحهٔ اول‌شان وامبی است؛ پیش‌فرض `vambi.ir,www.vambi.ir` |
| `CORS_ORIGINS` | بک‌اند | باید `https://vambi.ir` را داشته باشد |
| `NEXT_PUBLIC_MAIN_SITE` | فرانت | `https://60online.ir` برای لینک «مشاهده و خرید» |
| `STOREFRONT_PRICE_VISIBILITY` | بک‌اند | دیده‌شدن قیمت؛ روی وامبی هم اعمال می‌شود |
| `KAVENEGAR_SENDER` | بک‌اند | شمارهٔ خط پیامک متنی هشدارها |
| `PRICE_ALERT_USER_DAILY_SMS` | بک‌اند | سقف پیامک خلاصه برای هر نفر در روز، خریدار و فروشنده با هم (پیش‌فرض ۲) |
| `SSO_ALLOWED_ORIGINS` | بک‌اند | (اختیاری) دامنه‌های مجاز ورود مشترک، با کاما، دقیقاً مثل `https://vambi.ir`. پیش‌فرض: `https://<VAMBI_DOMAIN>` و `https://www.<VAMBI_DOMAIN>`. در production فقط https پذیرفته می‌شود |
| `SSO_ALLOW_LOCALHOST` | بک‌اند | فقط برای توسعه: با `1` (و فقط بیرون از production)، `http://localhost` و `http://127.0.0.1` هم مقصد مجاز ورود مشترک می‌شوند. پیش‌فرض: خاموش |
| `PRICE_ALERT_DAILY_SMS_PARTS_CAP` | بک‌اند | سقف روزانهٔ بخش‌های پیامک خریدارها (پیش‌فرض ۱۵۰۰) |
| `PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP` | بک‌اند | سقف جدا برای فروشنده‌ها (پیش‌فرض ۵۰۰) |
| `PRICE_ALERT_JOB_BUDGET_S` | بک‌اند | حداکثر زمان هر اجرای کار ساعتی (پیش‌فرض ۱۲۰ ثانیه) |

## برای استقرار روی vambi.ir
1. DNS دامنهٔ vambi.ir به همان سرور فرانت، و گواهی SSL.
2. `https://vambi.ir` در `CORS_ORIGINS`.
3. ورود مشترک با 60online.ir. بدون آن، کاربر روی وامبی جدا وارد می‌شود (حساب همان حساب شصت آنلاین است، فقط نشست جداست).
4. تنظیم `KAVENEGAR_SENDER` برای پیامک هشدارها.

## تصمیم دامنه (۱۷ آبان ۱۴۰۵)
- **تصمیم کارن:** وامبی از روز اول روی `vambi.ir`، با همان حساب و همان سرور شصت آنلاین.
- **کار کارن:** تنظیم دامنه (DNS، SSL، اتصال به سرور).
- **کار ما:** ورود مشترک vambi.ir و 60online.ir قبل از راه‌اندازی، و چک نهایی وامبی روی دامنه.

## چک‌لیست راه‌اندازی وامبی (باید حتماً چک شود)
- ⏳ DNS و SSL دامنهٔ vambi.ir (کارن)
- ⏳ `https://vambi.ir` در `CORS_ORIGINS`، و `vambi.ir,www.vambi.ir` (بدون https) در `VAMBI_HOSTS` روی سرور
- ⏳ ورود مشترک دو دامنه: ساخته شد؛ مانده: بازبینی امنیتی، QA، و تست روی دامنهٔ واقعی (`NEXT_PUBLIC_MAIN_SITE=https://60online.ir` باید در build فرانت باشد)
- ⏳ `KAVENEGAR_SENDER` و تست یک پیامک واقعی
- ✅ QA نهایی هشدار قیمت: قبول شد (۱۷ آبان)؛ جزئیات در PROGRESS.md
- ⏳ تست مایگریشن‌های 0079 و 0080 روی PostgreSQL واقعی
- ⏳ PR از `marketplace-roadmap` به `main` (این کارها هنوز در main نیستند؛ تداخلی با صفحهٔ اول جدید ندارند)
- ⏳ استقرار روی سرور (فقط با تأیید کارن)

## محدودیت‌های شناخته‌شده
- **پراکسی پیش‌نمایش فقط‌خواندنی است:** `frontend/src/app/api/v1/[...path]/route.ts` (پراکسی Next.js به Flask، برای پیش‌نمایش) فقط GET/HEAD/OPTIONS را رد می‌کند (به‌جز سازندهٔ پک) و بقیه را با `405 preview_read_only` جواب می‌دهد. پس در پیش‌نمایش، «زیر نظر بگیر»، تنظیمات هشدار و ورود مشترک (`/auth/sso/*`) کار نمی‌کنند. این عمداً تغییر داده نشد؛ روی سرور اصلی Caddy مسیر `/api/*` را مستقیم به Flask می‌دهد و این محدودیت وجود ندارد.
- صفحهٔ `/sso/callback` بیرون از `/vambi` است، پس قاب مشترک سایت (هدر/فوتر شصت آنلاین) زیرش رندر می‌شود؛ خود صفحه با یک پنل تمام‌صفحه آن را می‌پوشاند و فقط چند لحظه دیده می‌شود.

## اگر کار نیمه‌کاره ماند (برای جلسهٔ بعدی)
- شاخه: `marketplace-roadmap`. آخرین وضعیت در [PROGRESS.md](PROGRESS.md) و چک‌لیست بالا.
- قدم بعدی: QA قبول شده؛ ورود مشترک دو دامنه را بساز و ۳ نکتهٔ باقی‌ماندهٔ QA را در PROGRESS.md ببین.
