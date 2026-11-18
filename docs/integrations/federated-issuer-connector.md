# رابط صادرکننده (Issuer Connector) — پذیرش اعتبار صادرشدهٔ شصت‌آنلاین در ونداپی

وضعیت: **استاب رابط، خاموش به‌طور پیش‌فرض.** درخواست‌ها احراز و اعتبارسنجی می‌شوند و سپس `501 issuer_not_implemented` می‌گیرند. هیچ مانده‌ای خوانده و هیچ پولی جابه‌جا نمی‌شود.
تصمیم پشت آن: `docs/decisions/2026-11-18-federated-credit-vandapay.md`.

> **هم‌ترازی لازم:** این قرارداد پیشنهاد حداقلی شصت‌آنلاین است. سند ونداپی
> `docs/integration-plans/federated-credit/ISSUER-CONNECTOR.md` هنگام نوشتن در دسترس نبود؛ پیش از هر پیاده‌سازی واقعی، نام مسیرها، فیلدها، کدهای خطا و رویدادها باید با آن یکی شود.

- کد: `backend/app/services/federated_issuer_service.py`، مسیرها: `backend/app/api/v1/federated_issuer.py`
- آزمون: `backend/tests/test_vandapay_federated.py::IssuerStubTest`

## پرچم‌ها
| متغیر | توضیح |
| --- | --- |
| `FEDERATED_ISSUER_ENABLED` | `1` = روشن. پیش‌فرض خاموش ← همهٔ مسیرها ۴۰۴ |
| `FEDERATED_ISSUER_SECRET` | رمز مشترک با ونداپی (حداقل ۱۶ نویسه)؛ بدون آن خاموش |

## امنیت
- سرآیند `VandaPay-Signature: t=<unix>,v1=<hex>` با `HMAC_SHA256(secret, t + "." + raw_body)`، تحمل ۳۰۰ ثانیه، چند `v1` برای چرخش رمز (همان طرح وب‌هوک ونداپی).
- `Idempotency-Key` برای همهٔ عملیات نوشتنی الزامی است.
- مبالغ ریال صحیح؛ ارز فقط `IRR`؛ موبایل `09xxxxxxxxx`.

## مسیرها (همه POST، JSON)
| مسیر | بدنه | پاسخ هدف (پس از پیاده‌سازی) |
| --- | --- | --- |
| `/api/v1/federation/issuer/eligibility` | `{customer_phone, program_ref, amount, currency, items?}` | `{eligible, spendable_amount ≤ amount}` — هرگز کل مانده |
| `/api/v1/federation/issuer/authorizations` | `{authorization_ref, customer_phone, program_ref, amount, currency, order_ref, merchant_ref, items?}` | `201 {authorization_id, status:"authorized", amount, expires_at}` |
| `…/authorizations/<id>/capture` | `{amount}` | برداشت قطعی از دفتر شصت‌آنلاین |
| `…/authorizations/<id>/void` | `{}` | آزادسازی نگه‌داشت |
| `…/authorizations/<id>/refunds` | `{amount, refund_ref}` | بازگشت به همان برنامه |

`items[]` (اختیاری) با `{amount, category, …}`؛ `sum(items.amount) == amount` وگرنه `422 items_total_mismatch`.

## وب‌هوک خروجی (شصت‌آنلاین → ونداپی)
سرآیند `SixtyOnline-Signature` با همان طرح امضا. رویدادها: `issuer.authorization.expired`، `issuer.authorization.voided`، `issuer.program.suspended`. فقط سازندهٔ پاکت و امضا (`build_outbound_event`) وجود دارد؛ چیزی ارسال نمی‌شود.

## کار باقی‌مانده برای روشن کردن واقعی
1. هم‌ترازی قرارداد با سند ونداپی.
2. نگاشت `program_ref` به برنامه‌های داخلی (`welfare_plans` / تخصیص اعتبار) و ثبت این‌که کدام برنامه «فدرال» است.
3. جدول مجوزها (نیاز به مایگریشن — تأیید مالک) و اتصال به `credit_service` / `welfare_wallet_service` با همان قفل‌های `BEGIN IMMEDIATE`.
4. صف ارسال وب‌هوک خروجی (می‌تواند از `partner_webhook_service` الگو بگیرد).
5. رضایت ثبت‌شدهٔ کاربر برای استعلام `eligibility` با موبایل.
