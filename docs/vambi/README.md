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
| ورود مشترک با شصت آنلاین | مانده (لازم اگر وامبی روی دامنهٔ جدا باشد) |
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
| `PRICE_ALERT_USER_DAILY_SMS` | بک‌اند | سقف پیامک خلاصه برای هر کاربر در روز (پیش‌فرض ۲) |
| `PRICE_ALERT_DAILY_SMS_PARTS_CAP` | بک‌اند | سقف روزانهٔ بخش‌های پیامک خریدارها (پیش‌فرض ۱۵۰۰) |
| `PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP` | بک‌اند | سقف جدا برای فروشنده‌ها (پیش‌فرض ۵۰۰) |
| `PRICE_ALERT_JOB_BUDGET_S` | بک‌اند | حداکثر زمان هر اجرای کار ساعتی (پیش‌فرض ۱۲۰ ثانیه) |

## برای استقرار روی vambi.ir
1. DNS دامنهٔ vambi.ir به همان سرور فرانت، و گواهی SSL.
2. `https://vambi.ir` در `CORS_ORIGINS`.
3. ورود مشترک با 60online.ir. بدون آن، کاربر روی وامبی جدا وارد می‌شود (حساب همان حساب شصت آنلاین است، فقط نشست جداست).
4. تنظیم `KAVENEGAR_SENDER` برای پیامک هشدارها.

## تصمیم باز: دامنه از روز اول یا بعداً
- **پیشنهاد:** وامبی از روز اول روی `vambi.ir` باشد، با همان حساب و همان سرور، و ورود مشترک قبل از راه‌اندازی ساخته شود. جابه‌جا کردن بعدی لینک‌ها، پیامک‌ها و جایگاه گوگل را خراب می‌کند.
- **گزینهٔ دیگر:** فعلاً روی `60online.ir/vambi` و بعداً انتقال با ریدایرکت ۳۰۱.
- منتظر تصمیم کارن.
