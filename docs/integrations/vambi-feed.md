# فید فقط‌خواندنی وامبی و ورود مشترک (قرارداد v2)

وامبی (vambi.ir) محصول جداگانهٔ گروه است. شصت آنلاین برای آن فقط دو چیز می‌دهد: یک فید فقط‌خواندنی سرور به سرور و نقطهٔ ورود مشترک (SSO).
قرارداد کامل در ریپوی خصوصی وامبی است (`docs/FEED-SPEC-60ONLINE.md`، نسخهٔ v2). این فایل فقط خلاصهٔ سمت شصت آنلاین است.

## سطح‌های قیمت (مدل واقعی شصت آنلاین)

| tier | منبع در DB | چه کسی می‌بیند |
| --- | --- | --- |
| `public` | `seller_offers.selling_price_minor` روی کانال retail + `offer_price_tiers` با `channel=retail` و بدون سازمان (تخفیف تعدادی) | همه (`STOREFRONT_PRICE_VISIBILITY=public`) |
| `wholesale` | همان قیمت پایه روی کانال organization + `offer_price_tiers` با `channel=organization` و بدون سازمان | عضو فعال هر حساب کسب‌وکار (سازمان یا فروشگاه طرف قرارداد) |
| `org` | `offer_price_tiers` با `organization_id` | فقط اعضای همان سازمان |

قیمت فقط تا ۲۴ ساعت پس از تأیید فروشنده معتبر است. `contract` قیمت عمومی ندارد؛ `rfq_only`، `out_of_stock` و `unavailable` هیچ قیمتی ندارند.
قیمت تمام‌شده، کمیسیون، کوپن و تخفیف شرکا هرگز در فید نیست.

## endpointها

| مسیر | توضیح |
| --- | --- |
| `GET /api/v1/feeds/vambi/products` | فید؛ `updated_since`، `cursor`، `limit` (۱ تا ۵۰۰). احراز هویت Bearer سرور به سرور. تا تنظیم نشدن توکن خاموش است (۴۰۴). |
| `POST /api/v1/auth/sso/issue` | کاربر واردشده، پس از کلیک در `/sso/vambi`، کد یک‌بارمصرف ۶۰ ثانیه‌ای برای origin مجاز می‌گیرد. |
| `POST /api/v1/auth/sso/exchange` | وامبی کد را سرور به سرور (با هدر Origin) تعویض می‌کند؛ پاسخ شامل `user_ref` (مرجع پایدار کاربر) و `pricing_context` است. |
| `POST /api/v1/sso/vambi/entitlements` | تازه‌سازی مجوز قیمت بدون ورود دوباره: `{user_ref}` با همان توکن سرور به سرور ← `pricing_context` **فعلی** (عضویت لغوشده/حساب غیرفعال ← مجوز کمتر). |

`pricing_context` برای هر عضویت فعال در حساب کسب‌وکار فعال: `org_id`، `org_name`، `buyer_kind`، **`role`** (`employee` / `organization_admin` / `procurement_agent` / `organization_finance`)، `procurement_role`، و پرچم‌های `is_admin`، `can_buy_for_org`، `can_approve_purchases`، `can_manage_finance`، `pack_beneficiary` (برنامهٔ پک/سبد رفاهی باز)، `welfare_plan_active`، `credit_allocation_active` — همه از همان کنترل‌های پنل سازمان؛ بدون مبلغ و بدون دادهٔ شخصی.

کد: `backend/app/services/vambi_feed_service.py`، `backend/app/api/v1/vambi_feed.py`، `backend/app/services/sso_service.py`، `frontend/src/app/sso/vambi/page.tsx`.
تست: `backend/tests/test_vambi_feed.py`، `backend/tests/test_sso.py`، `backend/tests/test_vambi_entitlements.py`.

## env (برای استقرار، با تأیید مالک)

| متغیر | مقدار |
| --- | --- |
| `STOREFRONT_PRICE_VISIBILITY` | `public` (تصمیم مالک ۱۴۰۵/۰۸/۲۱) |
| `VAMBI_FEED_TOKEN` | رشتهٔ تصادفی ≥ ۳۲ نویسه؛ همان مقدار در env وامبی. برای چرخش: `جدید,قدیم` |
| `VAMBI_FEED_RATE_PER_MIN` | اختیاری، پیش‌فرض ۶۰ |
| `VAMBI_ENTITLEMENTS_RATE_PER_MIN` | اختیاری، پیش‌فرض ۶۰۰ |
| `SSO_ALLOWED_ORIGINS` | `https://vambi.ir,https://www.vambi.ir` |

مایگریشن: `0082_sso_codes.sql` (فقط ساخت جدول `sso_codes`؛ غیرمخرب). فید هیچ مایگریشنی ندارد.

## محدودیت‌های شناخته‌شده
- چند مسیر قدیمی مدیریت کالا را بدون تغییر زمان‌مهر عوض می‌کنند؛ وامبی باید روزی یک بار sweep کامل (بدون `updated_since`) بزند.
- `user_ref` با `SECRET_KEY` امضا می‌شود؛ با چرخش این کلید مرجع‌های قدیمی ۴۰۴ می‌گیرند و کاربر یک بار دوباره وارد می‌شود.
- سقف نرخ فید در حافظهٔ هر process است (مثل بقیهٔ سقف‌های فعلی برنامه)؛ با چند worker، سقف مؤثر چند برابر می‌شود.
- مالیات با نرخ استاندارد محاسبه می‌شود، مثل storefront؛ دستهٔ مالیاتی اختصاصی کالا (`tax_product_assignments`) هنوز در نمایش قیمت لحاظ نمی‌شود.
