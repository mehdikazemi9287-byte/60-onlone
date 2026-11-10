# راهنمای انتشار هشدار قیمت، شبکهٔ فروش و SSO (بک‌اند + فرانت)

**تاریخ:** ۱۹ آبان ۱۴۰۵ (2026-11-10) · **شاخه:** `fix/audit-2026-11-10` (شامل vambi-sso + اصلاح‌های main) · **یافته‌ها:** SO-01، N2

> این سند فقط برنامه است. **هیچ استقراری انجام نشده.** هر گام «switch» و «rollback» تأیید صریح مالک را لازم دارد (AGENTS.md قاعدهٔ ۱۱ و ۱۲).

## ۱. چه چیزی منتشر می‌شود
- بک‌اند: migrationهای `0079` تا `0083`
  - 0079 تا 0080: هشدار قیمت
  - 0081: شبکهٔ فروش
  - 0082: کدهای SSO
  - 0083: چرخهٔ وضعیت پیامک هشدار قیمت. جدول‌های `price_alert_events` و `price_alert_sms` در SQLite بازسازی می‌شوند، بدون حذف ردیف.
- وابستگی تازهٔ بک‌اند: `Pillow==13.0.0` در `backend/requirements.txt`.
- فرانت: صفحه‌های هشدار قیمت، شبکه، SSO و اصلاح متن اعتماد قیمت (SO-04).

**نکتهٔ مهم:** `backend/entrypoint.sh` هنگام بالا آمدن بک‌اند خودش migration را اجرا می‌کند. پس هر بالا آمدن image جدید روی DB زنده یعنی اجرای 0079 تا 0083 روی دادهٔ واقعی. اول همیشه روی کپی.

## ۲. پیش‌نیازها (مالک / devops)
1. یک SHA مشخص از همین شاخه، پس از QA مستقل و ادغام در main، انتخاب و یادداشت شود. کل vambi-sso جایگزین main نشود.
2. در فایل env بک‌اند سرور، این متغیرها تنظیم شوند:
   - `SMS_PROVIDER=kavenegar`
   - `KAVENEGAR_API_KEY`
   - `KAVENEGAR_TEMPLATE`
   - `KAVENEGAR_SENDER`
   - چرا: از این نسخه فرستندهٔ console بیرون از development/test رد می‌شود (N1). اسکریپت upgrade روی سرور `APP_ENV=staging` می‌گذارد. بدون این تنظیم، ورود پیامکی پیام خطای صریح می‌دهد و هشدار پیامکی `unavailable` ثبت می‌شود.
3. میرور PyPI در دسترس سرور باشد (pypi.org از سرور باز نیست). `Pillow==13.0.0` در میرور باشد. اگر نبود، نسخهٔ موجود 12.x با تأیید جایگزین و یک بار تست شود.
4. بکاپ تازهٔ DB و پوشهٔ media گرفته شود.

## ۳. تمرین روی کپی DB (سایت زنده دست نمی‌خورد)
```bash
sudo bash deploy/sqlite-upgrade.sh stage "<PIP mirror URL>"
```
- این حالت DB زنده را کپی می‌کند و نسخهٔ جدید را روی پورت‌های جدا بالا می‌آورد.
- بک‌اند با میرور ساخته می‌شود و migrationها روی کپی اجرا می‌شوند.

کنترل‌ها روی نسخهٔ stage:
- [ ] لاگ بک‌اند: `→ applying migrations` بدون خطا. در `schema_migrations` آخرین نسخه `0083` باشد.
- [ ] `PRAGMA integrity_check` و `PRAGMA foreign_key_check` روی کپی: `ok` و خالی.
- [ ] تعداد ردیف جدول‌های اصلی (orders، products، users، seller_offers) قبل و بعد برابر باشد.
- [ ] `GET /api/v1/health` کد ۲۰۰ بدهد.
- [ ] `python -c "import PIL"` داخل container بک‌اند خطا ندهد. آپلود یک تصویر آزمایشی در پنل مدیریت stage موفق باشد.
- [ ] `python -m scripts.launch_preflight` اجرا شود و BLOCKERها با وضعیت مورد انتظار مقایسه شوند.
  - مورد انتظار: APP_ENV و درگاه سپهر تا راه‌اندازی فروش هنوز BLOCKER هستند (SO-07).
  - SMS_PROVIDER و Pillow نباید BLOCKER باشند.
- [ ] صفحه‌های `/`، `/sell`، `/benefits`، یک صفحهٔ محصول، `/me/price-alerts` و `/network` روی stage کد ۲۰۰ بدهند.
- [ ] در stage هیچ پیامکی به مشتری واقعی نرود. compose ساخته‌شده با `sqlite-upgrade.sh` سرویس worker ندارد؛ worker را روی stage بالا نیاورید.

## ۴. انتشار (فقط با تأیید صریح مالک)
```bash
sudo bash deploy/sqlite-upgrade.sh switch "<PIP mirror URL>"
```
- این گام بکاپ تازه می‌گیرد، استک قدیم را متوقف می‌کند و نسخهٔ جدید را روی DB زنده بالا می‌آورد.
- بک‌اند و فرانت هر دو ساخته می‌شوند. فقط ساختن فرانت (`--no-deps frontend`) کافی نیست.
- پس از switch، همهٔ کنترل‌های بخش ۳ روی دامنهٔ اصلی تکرار شوند.
- SHA مستقر و زمان انتشار در `docs/audits/customer-journey-2026-11-09.md` یا یک سند استقرار تازه ثبت شود.

## ۵. برگشت (rollback)
```bash
sudo bash deploy/sqlite-upgrade.sh rollback
```
- این گام استک جدید را متوقف می‌کند، کپی DB پیش از switch را برمی‌گرداند و استک قدیم را بالا می‌آورد.
- هشدارها، رویدادها و ثبت‌نام‌هایی که بعد از switch ساخته شده‌اند، با برگشت DB از بین می‌روند. پیش از تصمیم، مالک این را بداند.
- migrationها ستون/جدول اضافه می‌کنند. کد قدیم به جدول‌های تازه کاری ندارد. با این حال برگشت DB امن‌ترین راه است.

## ۶. پس از انتشار
- **worker:** compose ساخته‌شده با `sqlite-upgrade.sh` فقط backend و frontend دارد. job ساعتی `run_price_alerts` در `scripts/scheduler.py` فقط با container worker اجرا می‌شود (`entrypoint.sh worker`، همان image).
  - افزودن worker به استک زنده یک تصمیم جداست و تأیید مالک را لازم دارد.
  - پیش از آن، تنظیمات بند ۲ (پیامک) باید کامل باشد.
- [ ] job هشدار قیمت در worker یک بار در ساعت‌های غیرسکوت اجرا شود. در `price_alert_sms` وضعیت `sent` با `provider_ref` دیده شود.
- [ ] ردیف `sending` قدیمی‌تر از ۱۵ دقیقه نماند. `recover_stuck` آن را `unknown` می‌کند.
- [ ] شمار `unknown` و `failed` روزانه پایش شود.
