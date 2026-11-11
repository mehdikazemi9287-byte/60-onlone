# استقرار وامبی روی سرور — راهنمای قدم‌به‌قدم

برای کارن. هر قدم یک «بررسی» دارد؛ تا بررسی سالم نشده، قدم بعد را نرو. اگر جایی خطا دیدی، همان‌جا بایست و خروجی را بفرست.

**مرحلهٔ الف (این راهنما):** وامبی با همین پشتهٔ سرور شصت آنلاین روی `vambi.ir` بالا می‌آید. سرویس جدیدی لازم نیست: Caddy دامنهٔ vambi.ir را به همان فرانت می‌دهد و فرانت صفحهٔ وامبی را نشان می‌دهد.
**مرحلهٔ ب (بعداً):** برنامهٔ مستقل وامبی (ریپوی `vambi`) به‌عنوان سرویس جدا. آخر همین فایل.

---

## ۰. پیش از شروع (روی گیت‌هاب و پنل‌ها)
1. **ادغام PRها به ترتیب:** اول [#12](https://github.com/mehdikazemi9287-byte/60-onlone/pull/12)، بعد [#19](https://github.com/mehdikazemi9287-byte/60-onlone/pull/19). هر دو الان بدون تداخل‌اند. (#21 جداست و به وامبی ربطی ندارد.)
2. **QA نهایی:** انجام شد (۲۱ آبان) و یافته‌هایش رفع شد؛ جزئیات در [PROGRESS.md](PROGRESS.md).
3. **DNS:** رکورد A برای `vambi.ir` و `www.vambi.ir` به IP همان سرور شصت آنلاین.
   - بررسی (روی کامپیوتر خودت): `nslookup vambi.ir` باید IP سرور را بدهد.
4. **خط پیامک:** شمارهٔ خط ارسال کاوه‌نگار آماده باشد (برای `KAVENEGAR_SENDER`). بدون آن هم استقرار انجام می‌شود، فقط پیامک هشدار نمی‌رود و اعلان داخل سایت می‌رود.

## ۱. ورود به سرور و پیدا کردن پوشه
```bash
cd <پوشهٔ ریپو روی سرور>      # همان جایی که آخرین بار استقرار کردی؛ داخلش پوشهٔ deploy هست
git status --short             # باید خالی باشد؛ اگر نیست، بایست و خروجی را بفرست
git log --oneline -1           # نسخهٔ فعلی را جایی یادداشت کن (برای برگشت)
```

## ۲. پشتیبان (حتماً)
```bash
cd deploy
docker compose -f docker-compose.prod.yml exec backup /bin/sh /backup.sh
```
بررسی: پیام موفقیت و یک فایل تازه در پوشهٔ پشتیبان. **بدون پشتیبان سالم ادامه نده** (۵ مهاجرت دیتابیس اجرا می‌شود: 0079 تا 0083).

## ۳. گرفتن کد جدید
```bash
cd ..
git fetch origin && git checkout main && git pull --ff-only
git log --oneline -1           # باید commit ادغام PR #19 باشد
cd deploy
```

## ۴. تنظیمات `.env`
`nano .env` و این خط‌ها را چک یا اضافه کن (هیچ‌کدام را در گیت‌هاب نگذار):
```
VAMBI_DOMAIN=vambi.ir
CORS_ORIGINS=https://60online.ir,https://vambi.ir
KAVENEGAR_SENDER=<شمارهٔ خط ارسال>
PRICE_ALERT_USER_DAILY_SMS=2
PRICE_ALERT_DAILY_SMS_PARTS_CAP=1500
PRICE_ALERT_SELLER_DAILY_SMS_PARTS_CAP=500
PRICE_ALERT_JOB_BUDGET_S=120
```
- `STOREFRONT_PRICE_VISIBILITY` را عوض نکن مگر تصمیمش را گرفته باشی (الان `organizations`: قیمت فقط برای اعضا).
- `SSO_ALLOW_LOCALHOST` **نباید** روی سرور باشد.
- `SSO_ALLOWED_ORIGINS` لازم نیست؛ خودش از `VAMBI_DOMAIN` ساخته می‌شود.

## ۵. چک فایل Caddy (حتماً قبل از ساخت)
بخش لاگ Caddy تغییر کرده و با خود Caddy آزموده نشده. یک فایل خراب، کل سایت را پایین می‌آورد.
```bash
docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```
بررسی: آخر خروجی `Valid configuration`. اگر خطا داد، **بایست** و خروجی را بفرست.

## ۶. ساخت و اجرا
```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```
بررسی: همهٔ سرویس‌ها `running` یا `healthy`. اگر backend بالا نیامد:
`docker compose -f docker-compose.prod.yml logs --tail=80 backend`

## ۷. بررسی بعد از استقرار
```bash
docker compose -f docker-compose.prod.yml exec backend python -m scripts.launch_preflight
docker compose -f docker-compose.prod.yml exec backend python -m scripts.vambi_readiness
```
- `launch_preflight`: نباید `BLOCKER` داشته باشد (مهاجرت‌ها همه اجرا شده باشند).
- `vambi_readiness`: می‌گوید چند کالا قیمت معتبر از دست‌کم دو فروشنده دارد (هدف: ۵۰). اگر کمتر بود، سایت کار می‌کند ولی **هنوز اطلاع‌رسانی عمومی نکن**.

در مرورگر:
1. `https://vambi.ir` باز شود، قفل HTTPS سبز. (اولین بار گرفتن گواهی ممکن است یکی‌دو دقیقه طول بکشد.)
2. یک کالا جستجو کن؛ نتیجه با فروشنده‌ها بیاید.
3. «ورود با حساب شصت آنلاین» → در 60online.ir وارد شو → «ادامه در وامبی» → برگشت به وامبی با نام خودت.
4. روی یک کالا «زیر نظر بگیر» بزن، بعد `https://60online.ir/me/price-alerts` را ببین.
5. `https://www.vambi.ir` باید به `https://vambi.ir` برود.
6. صفحهٔ اول 60online.ir مثل قبل باشد.

بعد از چند ساعت: `docker compose -f docker-compose.prod.yml logs --since 3h worker | grep -i price_alert` باید اجرای ساعتی هشدارها را نشان دهد.

## ۸. اگر خراب شد (برگشت)
```bash
cd <پوشهٔ ریپو> && git checkout <commit یادداشت‌شده در قدم ۱> && cd deploy
docker compose -f docker-compose.prod.yml up -d --build
```
مهاجرت‌های 0079 تا 0083 فقط جدول و ستون اضافه می‌کنند و داده‌ای را عوض نمی‌کنند؛ معمولاً برگشت کد کافی است. اگر مشکل دیتابیس دیدی، از پشتیبان قدم ۲ بازیابی کن (`docs/DEPLOY.md` بخش ۶) و قبلش خبر بده.

## ۹. بعد از استقرار
- نتیجه را (موفق یا خطا، و خروجی `vambi_readiness`) بفرست تا در گزارش ثبت شود.
- اطلاع‌رسانی عمومی طبق `docs/vambi-comms-plan.md`، فقط وقتی آمادگی قبول شد.

---

## مرحلهٔ ب: برنامهٔ مستقل وامبی (بعداً)
پیش‌نیاز: ریپوی خالی `vambi` ساخته شود و دسترسی Claude به آن باز شود (کد الان روی شاخهٔ موقت `vambi-standalone` است).
طرح: یک سرویس `vambi-web` در `docker-compose.prod.yml` که از پوشهٔ ریپوی `vambi` ساخته می‌شود (`VAMBI_API_ORIGIN=http://backend:8000`، `NEXT_PUBLIC_MAIN_SITE=https://60online.ir`) و تغییر بلوک `{$VAMBI_DOMAIN}` در Caddy از فرانت شصت آنلاین به این سرویس. آن را جدا آماده و آزمایش می‌کنیم؛ با مرحلهٔ الف قاطی نشود.
