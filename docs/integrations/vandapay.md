# پرداخت با ونداپی (VandaPay)

وضعیت: **کد و آزمون خودکار آماده؛ خاموش به‌طور پیش‌فرض؛ هنوز روی هیچ سروری فعال نشده است.**

## چیست
ونداپی درگاه اعتباری و هماهنگ‌کنندهٔ پرداخت گروه است (PSP نیست). مشتری در صفحهٔ ونداپی یک سفارش را با اعتبار سازمانی، کارت هدیه، اعتبار باشگاه و باقی را با کارت بانکی می‌پردازد. در شصت‌آنلاین یک درگاه «هدایت به صفحهٔ پرداخت» دیگر است، مثل سپهر و اعتبار بیرونی؛ مسیر پرداخت تازه‌ای در سفارش اضافه نشده است.

- کد: `backend/app/adapters/payment/vandapay.py`، وب‌هوک: `backend/app/services/vandapay_webhook_service.py`، مسیرها در `backend/app/api/v1/orders.py`
- آزمون: `backend/tests/test_vandapay.py` (API ونداپی با یک شبیه‌ساز آزمایشی جایگزین شده است؛ بردارهای امضا از مخزن ونداپی در `backend/tests/fixtures/vandapay_webhook_vectors.json`)

## متغیرهای محیطی
| متغیر | الزامی | توضیح |
| --- | --- | --- |
| `VANDAPAY_SECRET_KEY` | بله | `sk_test_…` یا `sk_live_…`؛ فقط روی سرور |
| `VANDAPAY_WEBHOOK_SECRET` | بله | رمز وب‌هوک از پنل پذیرنده |
| `VANDAPAY_API_BASE` | خیر | پیش‌فرض `https://api.vandapay.ir/api/v1`؛ فقط https |
| `VANDAPAY_ENABLED` | خیر | `0` = خاموش، حتی اگر کلیدها تنظیم باشند |
| `PUBLIC_BASE_URL` | بله | نشانی https سایت؛ برای ساختن نشانی بازگشت |
| `VANDAPAY_CATEGORY_MAP` | خیر | JSON نگاشت slug دستهٔ شصت‌آنلاین → کد دستهٔ ونداپی (مثل `{"rice":"goods.livelihood"}`)؛ مقدار نامعتبر = ونداپی خاموش |
| `VANDAPAY_ORDER_CATEGORY` | خیر | `category` سطح سفارش؛ پیش‌فرض `goods` |
| `VANDAPAY_DEFAULT_ITEM_CATEGORY` | خیر | دستهٔ سطرهای بی‌نگاشت؛ پیش‌فرض `goods.general` |
| `VANDAPAY_ORG_CASH_ENABLED` | خیر | `1` = پرداخت سهم نقدی سفارش سازمانی با ونداپی؛ پیش‌فرض خاموش |

قواعد: بدون هر دو کلید خاموش است. `sk_live_` فقط با `APP_ENV=production` پذیرفته می‌شود. `sk_test_` در production رد می‌شود مگر `DEMO_MODE=1`، تا پرداخت آزمایشی هرگز سفارش واقعی نسازد. فقط وقتی روشن باشد گزینهٔ «پرداخت با ونداپی» در `GET /api/v1/checkout/payment-options` می‌آید.

## منبع پرداخت انحصاری (تصمیم مالک ۱۴۰۵/۰۸/۲۷)
با انتخاب ونداپی، کیف رفاهی و اعتبار سازمانی **داخلی** شصت‌آنلاین برای آن سفارش کسر نمی‌شوند و **کل سفارش** به ونداپی می‌رود؛ `use_welfare=true` همراه ونداپی خطای ۴۲۲ `funding_source_conflict` می‌گیرد. جزئیات: `docs/decisions/2026-11-18-federated-credit-vandapay.md`.

## بدنهٔ intent
`amount` (کل سفارش، ریال)، `order_ref`، `return_url`، `category`، `customer_phone` (فقط موبایل تأییدشدهٔ کاربر، فقط برای پیش‌پر کردن OTP ونداپی)، `items[]` و `metadata` (`source, invoice_id, price_tier, vat_bps, vat_rial, shipping_rial, funding`).
`items[]`: هر سطر `{sku, product_id, name, quantity, category, amount}`؛ تخفیف (۶۰کوین/خرید دوره‌ای) اول به‌نسبت روی سطرها پخش می‌شود، سپس VAT هر سطر = `base × rate_bps // 10000` و باقی‌ماندهٔ گرد کردن روی بزرگ‌ترین سطر؛ حمل یک سطر جدا (`SHIPPING`، `goods.general`، **بدون VAT** — تصمیم ۱۱ باز است). سطر جدای مالیات ساخته نمی‌شود. اگر `sum(items) != amount` باشد چیزی ارسال نمی‌شود.

## جریان
1. `POST /api/v1/checkout` با `"payment_provider": "vandapay"`: موجودی و اعتبار رزرو می‌شود و سرور `POST /payment_intents` را با مبلغ ریالی (تومان ×۱۰)، `order_ref = intent:<id>`، `return_url = …/api/v1/payments/vandapay/callback?invoice_id=<id>` و `Idempotency-Key` ثابت `60online-intent:<id>-invoice-<id>` می‌فرستد. پاسخ ۲۰۲ با `payment_redirect` به `checkout_url` است.
2. مشتری در ونداپی پرداخت می‌کند و به نشانی بازگشت برمی‌گردد. `?status=` و `pi=` مرورگر خوانده نمی‌شود؛ سرور شناسهٔ ونداپی را که خودش ذخیره کرده از API می‌خواند و فقط وقتی سفارش می‌سازد که وضعیت `succeeded`، مبلغ دقیقاً برابر، ارز IRR، بدون بازگشت وجه و حالت (test/live) برابر کلید باشد.
3. وضعیت‌های در انتظار (`processing`، `card_pending`، `unknown` و هر وضعیت ناشناخته) موفق حساب نمی‌شوند؛ رزرو می‌ماند تا وب‌هوک یا آزادسازی خودکار ۳۰ دقیقه‌ای.
4. وب‌هوک `POST /api/v1/payments/vandapay/webhook`: امضای بدنهٔ خام (HMAC-SHA256، مقایسهٔ زمان‌ثابت، ۵ دقیقه، چند `v1`)، حذف تکراری با `event.id` در جدول موجود `webhook_events` (بدون جدول یا migration تازه)، بازخوانی وضعیت از API و سپس همان تکمیل پرداخت. خطای موقت = ۵۰۳ تا ونداپی دوباره بفرستد.
5. پرداخت ناموفق، مبلغ نادرست یا موفقیت دیرهنگام پس از آزاد شدن رزرو: پیش از پرداخت لغو (`cancel`) و پس از پرداخت بازگشت کامل وجه با کلید ثابت.

## آزمون با sk_test_
1. `cd backend && python3 -m pytest -q tests/test_vandapay.py`
2. روی سرور آزمایشی (نه production): در پنل پذیرندهٔ ونداپی کلید `sk_test_` بسازید، نشانی وب‌هوک `https://<staging>/api/v1/payments/vandapay/webhook` را ثبت کنید و دو متغیر را تنظیم و سرویس را دوباره راه بیندازید.
3. با «ارسال وب‌هوک آزمایشی» پنل پاسخ ۲۰۰ بگیرید؛ یک خرید کوچک با گزینهٔ «پرداخت با ونداپی» انجام دهید و حالت‌های موفق، ناموفق و timeout درگاه آزمایشی را امتحان کنید؛ سپس بازگشت وجه.

## موانع پیش از فعال‌سازی واقعی
طبق `docs/PROGRESS.md` مخزن ونداپی، خود ونداپی هنوز فعال نیست:
- سرور ونداپی نصب نشده (دامنه، SSL، پشتیبان)؛ `api.vandapay.ir` هنوز در دسترس نیست
- ترمینال سپهر برای بخش کارت ونداپی گرفته و آزموده نشده است
- نرخ کمیسیون روش‌ها تعیین نشده (بدون آن کلید `sk_live_` صادر نمی‌شود)
- نظر حقوقی (پرسش‌های `docs/legal-drafts/` ونداپی) دریافت نشده است

## بازگشت وجه مرجوعی
- برای سفارشی که با ونداپی پرداخت شده، اقدام `refund` مرجوعی (`POST /api/v1/admin/returns/<id>/refund`) به‌جای واریز دستی، `POST /payment_intents/{id}/refunds` را با کلید ثابت `60online-return-<return_id>-<amount>` صدا می‌زند (خارج از تراکنش DB).
  - ۲۰۱ `succeeded` ← مرجوعی `refunded` (و سفارش در استرداد کامل `refunded`).
  - ۲۰۲ `pending` ← مرجوعی در `refund_pending` با `refund_reference=vandapay:<re_id>` می‌ماند؛ وب‌هوک `refund.succeeded` (پس از بازخوانی intent و تطبیق `refunded_amount`) آن را نهایی می‌کند؛ تکرار رویداد بی‌اثر است.
  - `refund.failed`/`refund.canceled` ← مرجع پاک و رویداد «اقدام دستی لازم» ثبت می‌شود. (تکرار همان مبلغ همان کلید را دارد و پاسخ قبلی ونداپی را برمی‌گرداند؛ پس از شکست، بازپرداخت را دستی ثبت کنید.)
  - ۴xx ونداپی (مثل `partial_refund_unsupported`) ← ۴۰۹ `gateway_refund_manual_review` و هیچ تغییری.
- ثبت دستی برای این سفارش‌ها فقط با `manual_override=true` (پس از بررسی) ممکن است؛ بدون آن ۴۰۹ `gateway_refund_required`.
- بازگشت وجهی که مستقیم در پنل ونداپی انجام شود (بدون مرجوعی در شصت‌آنلاین) فقط در `audit_logs` با `payment.refund_external` ثبت می‌شود و سفارش/دفتر را خودکار اصلاح نمی‌کند.

## سهم نقدی سفارش سازمانی (اختیاری، پرچم `VANDAPAY_ORG_CASH_ENABLED`)
- `POST /api/v1/orgs/<org>/orders/<id>/pay/vandapay` (فقط مالی/مدیر سازمان) برای سفارشی با `cash_status='due'` یک intent ونداپی با مبلغ `cash_due_minor` می‌سازد و `checkout_url` را برمی‌گرداند (همان «لینک پرداخت»). سفارش «نقدی کامل» با `items` کامل، سهم پیش‌پرداخت با یک سطر.
- بازگشت مرورگر: `GET /api/v1/payments/vandapay/org-cash/return?order_id=` ← بازخوانی سرور‌به‌سرور، سپس `finalize_paid` با provider `vandapay`؛ تغییر مسیر به `/organization/orders?payment=…`. وب‌هوک هم همین کار را می‌کند.
- پولی که پس از لغو/انقضا یا تأیید دستی رسید، با `reverse` برگردانده می‌شود.
- واریز بانکی + تأیید دستی (`confirm-payment`) مثل قبل در دسترس است.
- محدودیت: فرانت‌اند هنوز دکمه‌ای برای این مسیر ندارد.
