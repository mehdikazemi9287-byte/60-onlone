# 60ONLINE — گزارش اجرای داخلی (staging)
شروع: 2026-09-09 · worktree: /home/ubuntu/60online-staging-work (branch staging-impl-20260909)
staging frontend: 127.0.0.1:3064 (systemd 60online-staging-fe) · staging backend: 127.0.0.1:8064 (docker 60online-stg2-api, DB stage2/70online.db isolated)
restore point Production: /home/ubuntu/60online-restore-points/20260909T180812Z/  · Production BUILD_ID fvZI7bAvR3BMpOlIhbpzr (UNCHANGED)

## PHASE 1-2 — دسته‌بندی‌ها  [DONE, tested]
- /category همه ۲۰ دسته (۸ خالی با «در حال تکمیل محصولات»)، مرتب‌سازی دارای‌محصول-اول، عنوان «همه دسته‌بندی‌ها»
- CatalogBrowser: دسته خالی → «این دسته در حال تکمیل محصولات است.»
- صفحه اصلی: لینک «مشاهده همه ۲۰ دسته» (بدون بازطراحی) · Header: برچسب اصلاح شد
- هیچ حذف/ادغام دسته. appliance/appliances جدا.
- commits 9255abd, fde50fb · build PASS · routes 200

## PHASE 3 — دستیار خرید هوشمند  [DONE, tested]
- موتور قاعده‌محور src/lib/assistant.ts (بدون LLM): تشخیص دسته فارسی (۲۰ دسته)، بودجه min/max (میلیون/هزار/بین..تا/زیر/بالای)، برند واقعی از کاتالوگ، فقط-موجود، کلیدواژه، چندشرطی، امتیازدهی + دلیل match فارسی
- route: /assistant (UI) + /api/assistant (server، fetch از API واقعی /api/v1/products + /categories)
- وضعیت قیمت: verified/unpriced صریح · وضعیت خرید: purchasable/inquiry-only/unavailable صریح
- zero-result واقعی (مثلا «فقط کالاهای موجود» → ۰ چون هیچ کالایی in_stock نیست؛ «دوچرخه» → ۰)
- بدون SKU/قیمت/موجودی/برند/ادعای AI جعلی · Search و Homepage دست‌نخورده
- ۱۲ تست فارسی PASS (لپ‌تاپ+بودجه، روتر میکروتیک، آجیل تواضع، ماهی قزل‌آلا، برنج طبیعت، گوشی سامسونگ، یخچال اسنوا، کتری فیلیپس، بازه بودجه، فقط-موجود=۰، دوچرخه=۰، پسته احمدآقایی)
- commit 9a72920 · build PASS

## PHASE 4 — Smart Pack Builder  [DONE, tested]
- backend: migration 0029_saved_packs.sql (saved_packs + saved_pack_items) — staging DB only
- app/services/pack_service.py + app/api/v1/packs.py (blueprint registered)
- endpoints: list/create/get/rename/delete pack · PUT items (upsert + qty0=remove) · DELETE item · POST add-to-cart · POST proforma
- قیمت هر خط فقط از sale_eligibility (همان تست فروشگاه) → الان همه unpriced/inquiry-only (وضعیت واقعی)
- جمع کل فقط از خطوط verified · اقلام بدون قیمت صریح، total کاذب صفر
- add-to-cart: فقط اقلام purchasable؛ بقیه skipped با دلیل (هیچ اجبار)
- proforma: customer_requests kind=procurement، بدون quote جعلی
- staging backend rebuilt: image 60online-staging-backend:packs-v1 → container 60online-stg2-api:8064؛ frontend repointed 8062→8064
- frontend: /pack-builder (page + client) · lib/api.ts packs · homepage PackBuilder section به‌روزرسانی (placeholder → live، بدون بازطراحی) · nav links
- تست API کامل PASS (create/add/qty/rename/remove/get/add-to-cart[0 added,1 skipped با دلیل]/proforma[req#]/list/delete/cross-user 401)
- commit 62938a8 · build PASS · /pack-builder 200 · proxy /api/v1/packs PASS · search/home intact
