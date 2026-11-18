# رابط صادرکننده (Issuer Connector v1) — پذیرش اعتبار صادرشدهٔ شصت‌آنلاین در ونداپی

وضعیت: **استاب هم‌تراز با پروتکل، خاموش به‌طور پیش‌فرض.** سطح سیم (مسیرها، امضا در هر دو جهت، بدنه‌ها، وضعیت‌های مجاز) طبق قرارداد ونداپی پیاده شده است. اما هنوز **هیچ برنامهٔ اعتباری فدرالی، نگه‌داشت یا ثبت دفتری وجود ندارد**. برای همین رابط مثل صادرکننده‌ای پاسخ می‌دهد که برای هیچ‌کس اعتبار ندارد. هیچ مانده‌ای خوانده و هیچ پولی جابه‌جا نمی‌شود.

- قرارداد مرجع: مخزن ونداپی، `docs/integration-plans/federated-credit/ISSUER-CONNECTOR.md` (پیاده‌سازی مرجع: `backend/app/federated/protocol.py` و `reference_issuer.py`)
- تصمیم: `docs/decisions/2026-11-18-federated-credit-vandapay.md`
- کد: `backend/app/services/federated_issuer_service.py` و `backend/app/api/v1/federated_issuer.py`. آزمون: `backend/tests/test_vandapay_federated.py::IssuerStubTest`

## ثبت در ونداپی
`api_base` = `https://<host>/api/v1/federation/issuer` ← همهٔ فراخوانی‌ها `POST {api_base}/v1/<op>` هستند.

## پرچم‌ها
| متغیر | توضیح |
| --- | --- |
| `FEDERATED_ISSUER_ENABLED` | `1` = روشن. پیش‌فرض خاموش است و همهٔ مسیرها ۴۰۴ می‌دهند |
| `FEDERATED_ISSUER_SECRET` | رازی که ونداپی هنگام ثبت یک بار نشان می‌دهد (حداقل ۱۶ نویسه). بدون آن رابط خاموش است |
| `FEDERATED_ISSUER_ID` | اختیاری. اگر تنظیم شود، سرآیند `VandaPay-Issuer` باید با آن برابر باشد |
| `FEDERATED_ISSUER_LIVE` | تا `1` نشود، به درخواست‌های `mode:"live"` پاسخ ۴۰۳ داده می‌شود |

## سیم
- درخواست: سرآیندهای `VandaPay-Signature: t=..,v1=..` (HMAC-SHA256 روی بدنهٔ خام، تحمل ۳۰۰ ثانیه، چند `v1` مجاز)، `Idempotency-Key` (برای authorize، capture، void و refund الزامی) و `VandaPay-Issuer`.
- امضای نامعتبر ← ۴۰۱ و هیچ تغییری.
- همهٔ بدنه‌ها `protocol:"1"` و `mode:"test"|"live"` دارند. مبالغ ریال صحیح و `currency:"IRR"` است. موبایل به شکل `+989xxxxxxxxx` و فقط همراه `consent.consent_ref` پذیرفته می‌شود.
- پاسخ موفق: HTTP 200 با بدنهٔ JSON دارای `status`، امضاشده با `VandaPay-Issuer-Signature` روی بدنهٔ خام پاسخ. خطاها امضا ندارند؛ ونداپی در این حالت fail-closed رفتار می‌کند.

| op | پاسخ امروز (استاب) | پاسخ پس از پیاده‌سازی واقعی |
| --- | --- | --- |
| `eligibility` | `ok, eligible:false, max_amount:0, reasons:[no_credit_account]` | `max_amount ≤ amount` فقط برای همین پرداخت، هرگز کل مانده |
| `authorize` | `declined / no_credit_account` | `authorized` با مبلغ دقیق و `issuer_txn_id` و `expires_at`، یا `declined` |
| `capture` | `declined / authorization_not_found` | `captured` (تکرار بی‌اثر) |
| `void` | `not_found` (چیزی نگه داشته نشده) | `voided` / `not_found` / `already_captured` |
| `refund` | `declined / refund_exceeds` | `refunded` / `pending` / `declined` |
| `status` | `not_found` | `authorized` / `captured` / `voided` / `expired` / `declined` / `not_found` |

## رویدادهای خروجی (شصت‌آنلاین ← ونداپی)
مقصد: `POST {VANDAPAY_API}/api/v1/federated/issuers/{issuer_id}/events` با سرآیند `VandaPay-Issuer-Signature`. انواع رویداد: `balance.changed`، `authorization.voided`، `authorization.expired` و `authorization.captured`. فعلاً فقط سازندهٔ پاکت و امضا (`build_outbound_event`) وجود دارد و چیزی ارسال نمی‌شود.

## کار باقی‌مانده برای روشن کردن واقعی
1. نگاشت برنامهٔ فدرال به برنامه‌های داخلی (`welfare_plans` / تخصیص اعتبار) و مشخص کردن این‌که کدام برنامه در ونداپی پیشنهاد شود.
2. جدول یکتایی `authorization_ref` / `capture_ref` / `refund_ref` در پایگاه داده (نیاز به مایگریشن و تأیید مالک)، نگه‌داشت واقعی با `BEGIN IMMEDIATE`، و آزادسازی خودکار پس از `expires_at`.
3. اتصال به `credit_service` / `welfare_wallet_service`، تسویه با پذیرنده و ثبت حسابداری فروش اعتباری در دفتر شصت‌آنلاین.
4. صف ارسال رویدادهای خروجی، و allowlist آی‌پی سرور ونداپی.
5. آزمون انتها‌به‌انتها با صادرکنندهٔ مرجع و سرور آزمایشی ونداپی (`FEDERATED_CREDIT_ENABLED` سمت ونداپی).
6. محدودیت MVP ونداپی: اعتبار فدرال هنوز با کارت یا اعتبار ونداپی ترکیب نمی‌شود (`422 federated_not_combinable`).
