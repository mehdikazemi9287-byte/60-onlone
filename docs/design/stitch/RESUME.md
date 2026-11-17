# ادامه‌ی کار انتقال Stitch → Figma (برای جلسه‌ی بعد)

## داده‌ها کجا هستند
- GitHub (این پوشه): کد HTML هر ۳۲ صفحه + لوگو در `screens/`، پرامپت و مشخصات هر صفحه در `screens/manifest.json`، فهرست `index.html`، بسته‌ی کامل `stitch-60online-screens.zip`.
- Figma فایل `nU3vf0u1urj1ROKyVEzYqU`، صفحه‌ی «Stitch Screens»:
  - `23:3` لایه‌ی کد زنده — **هر ۳۳ مورد داخل Figma هست** (قابل مشاهده/کلیک).
  - `10:3` فهرست (قابل ویرایش).
  - فریم‌های قابل ویرایش در ردیف y=2000: 01، 02، 03، 04، 05، 08، 09، 10، 11، 12، 13، 14، 15، 16، 17.

## باقی‌مانده (فقط تبدیل به لایه‌ی قابل ویرایش)
06، 31، 32 (برگه‌های چاپی A4 — Extract «Current state» خروجی نمی‌دهد؛ «Select element» روی بدنه‌ی صفحه را امتحان کنید) و 07 (لوگو SVG با upload_assets).
بقیه‌ی صفحه‌ها (۲۸ مورد) انجام شده‌اند.

## روش سریع
1. `figma-extract-sequence.zip` را با `send_code_to_figma` (createLayer) در همان فایل import کنید (آپلود از مرورگر؛ محیط ابری به figma.com دسترسی ندارد).
2. در پیش‌نمایش آن لایه: ↻ رفرش ← صفحه‌ی بعدی خودکار باز می‌شود.
3. عرض لایه: دسکتاپ ۱۲۸۰، موبایل ۳۹۰ (ترتیب: 06، 18–26، 30–32 دسکتاپ؛ 27، 28، 29، 33 موبایل).
4. Extract designs ← Current state (~۲۵ ثانیه).
5. پس از پایان: با use_figma فونت `Material Symbols Outlined` را به `Material Symbols Rounded` تغییر دهید، فریم‌ها را نام‌گذاری و در ردیف y=2000 مرتب کنید.
6. لوگو (07): SVG را از `screens/07-ae7bc86b.svg` با upload_assets وارد کنید.

## کار بعدی: پک‌ساز (تصمیم کاربر ۲۵ آبان: «منتظر طرح Stitch، بعد پیاده‌سازی»)
- ✅ طرح‌های Stitch آماده و منتقل شد (۲۶ آبان): صفحه‌های ۳۹–۴۸ در `screens/` + manifest. ⏳ باقی: `3830f83c` (دسکتاپ با دستیار)، انتقال ۳۴–۴۸ به فیگما.
- پیاده‌سازی شروع شد روی `feat/pack-builder-stitch-2026-11-17` (مناسبت‌های مذهبی/خیریه/فرهنگی/لوازم‌التحریر + تست). مشخصات: `docs/design/pack-builder-b2b-features.md`.
- پس از آماده شدن: صفحه‌های جدید → `screens/` + manifest، فیگما (کد زنده + Extract).
- پیاده‌سازی روی شاخه‌ی جدا (نه main، بدون دیپلوی): `frontend/src/app/pack-builder/page.tsx` → `PackStudio.tsx` (۹۶ خط)، `BudgetBuilder.tsx`؛ بک‌اند `pack_builder_service.py` (suggest، basket_quote) و `saved_pack_drafts.py`.
- طبق AGENTS.md پک‌ساز بخش محافظت‌شده است؛ `PackBuilder.tsx`/`PackBuilderInteractive.tsx` صفحه‌ی خانه دست نخورد مگر با دستور صریح.
