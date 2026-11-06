# راه‌اندازی سرور تولید — شصت آنلاین + وامبی

یک سرور، با Docker. همه‌چیز در پوشهٔ `deploy/` است.

| سرویس | کار |
|---|---|
| `db` | PostgreSQL 16 (به بیرون باز نیست) |
| `backend` | API فلسک با gunicorn؛ موقع شروع مهاجرت‌ها را اجرا می‌کند |
| `worker` | کارهای زمان‌بندی‌شده + پایش و هشدار (`scripts/scheduler.py`) |
| `frontend` | Next.js برای هر دو دامنه (vambi.ir با middleware به صفحهٔ وامبی می‌رود) |
| `backup` | پشتیبان روزانهٔ دیتابیس و فایل‌ها + کپی بیرون از سرور |
| `caddy` | HTTPS خودکار برای 60online.ir و vambi.ir و هدایت `/api/*` به بک‌اند |

## ۱. پیش‌نیاز
- سرور اوبونتو ۲۲ یا ۲۴، حداقل ۴ هسته، ۸ گیگ رم، ۱۰۰ گیگ SSD. **دیتاسنتر داخل ایران** (درگاه پرداخت و پیامک به IP ایران نیاز دارند).
- رکورد A برای `60online.ir`، `www.60online.ir`، `vambi.ir`، `www.vambi.ir` به IP سرور.
- اگر Docker Hub در دسترس نیست: mirror داخلی (مثلاً آروان یا docker.iranserver) را در `/etc/docker/daemon.json` در `registry-mirrors` بگذارید.

## ۲. نصب
```bash
git clone <repo> && cd 60-onlone && git checkout marketplace-roadmap
cd deploy && sudo ./setup.sh      # بار اول فقط .env را با رمزهای تصادفی می‌سازد
nano .env                          # درگاه، کاوه‌نگار، ربات هشدار، ریموت پشتیبان
sudo ./setup.sh                    # ساخت، اجرا، preflight، اولین پشتیبان
```
ساخت مدیر اول:
```bash
docker compose -f docker-compose.prod.yml exec backend python -m scripts.create_admin admin@60online.ir "نام مدیر"
```

## ۳. کارهای خودکار (worker)
| کار | زمان |
|---|---|
| وب‌هوک شرکا | هر دقیقه |
| آزادسازی پرداخت‌های رهاشده | هر ۵ دقیقه |
| سبد اشتراکی (`run_recurring`) | روزانه ۶:۳۰ تهران |
| چرخهٔ اعتبار سازمان‌ها | روزانه |
| انقضای سکه | روزانه |
| حذف دادهٔ شخصی تاریخ‌گذشته | روزانه |

لاگ: `docker compose -f docker-compose.prod.yml logs -f worker`

## ۴. پایش و هشدار
worker هر ۵ دقیقه بررسی می‌کند: آماده‌بودن API، پاسخ سایت، فضای دیسک (زیر ۱۰٪)، سن آخرین پشتیبان (بیش از ۲۶ ساعت). هشدار به ربات **بله** یا تلگرام می‌رود:
- در بله یک ربات بسازید، توکن را در `ALERT_BOT_URL=https://tapi.bale.ai/bot<TOKEN>/sendMessage` و شناسهٔ گفتگو را در `ALERT_CHAT_ID` بگذارید.
- هر مشکل حداکثر ساعتی یک بار تکرار می‌شود و «برطرف شد» هم می‌آید.
- توصیه: یک پایشگر بیرونی هم (مثلاً uptime خارج از سرور) روی `https://60online.ir/api/v1/health/live` بگذارید تا خاموشی کامل سرور هم دیده شود.

## ۵. پشتیبان
- روزانه: `db-YYYYMMDD-HHMM.dump` (فرمت pg_dump -Fc، بعد از نوشتن خوانده و آزموده می‌شود) و `files-….tar.gz` (تصاویر و مدارک) در `/var/backups/sixty`؛ ۱۴ روز نگه داشته می‌شود.
- **بیرون از سرور (ضروری):** فایل `rclone.conf` را در `/var/backups/sixty/` بگذارید (مثلاً فضای ابری آروان، S3 سازگار) و `BACKUP_RCLONE_REMOTE=arvan:sixty-backups`.
- پشتیبان دستی: `docker compose -f docker-compose.prod.yml exec backup /bin/sh /backup.sh`

## ۶. تمرین بازیابی (هر ماه یک بار؛ تا انجام نشده، پشتیبان «وجود ندارد»)
```bash
cd deploy
F=/backups/db-YYYYMMDD-HHMM.dump
docker compose -f docker-compose.prod.yml exec backup sh -c "createdb restore_test && pg_restore --no-owner -d restore_test $F && psql -d restore_test -c 'select count(*) from orders'"
docker compose -f docker-compose.prod.yml exec backup dropdb restore_test
```
بازیابی واقعی (از کار افتادن دیتابیس):
```bash
docker compose -f docker-compose.prod.yml stop backend worker frontend
docker compose -f docker-compose.prod.yml exec backup sh -c "dropdb sixty && createdb sixty && pg_restore --no-owner -d sixty $F"
docker compose -f docker-compose.prod.yml start backend worker frontend
```
فایل‌ها: `tar -xzf files-….tar.gz` درون volumeهای `media` و `documents`.

## ۷. به‌روزرسانی نسخه
```bash
git pull && cd deploy
docker compose -f docker-compose.prod.yml exec backup /bin/sh /backup.sh     # اول پشتیبان
docker compose -f docker-compose.prod.yml up -d --build                       # مهاجرت‌ها خودکار
docker compose -f docker-compose.prod.yml exec backend python -m scripts.launch_preflight
```
برگشت: `git checkout <نسخهٔ قبل>` و دوباره `up -d --build`؛ اگر مهاجرت جدید داده را عوض کرده، از پشتیبان همان صبح بازیابی کنید.

## ۸. نکته‌های امنیتی
- `.env` فقط با دسترسی 600؛ هرگز در git.
- فایروال فقط ۲۲، ۸۰، ۴۴۳. ورود SSH فقط با کلید (`PasswordAuthentication no`).
- `TRUSTED_PROXY_HOPS=1` در compose تنظیم است (Caddy تنها پراکسی). اگر Cloudflare یا CDN آروان جلوی سرور گذاشتید، آن را ۲ کنید.
- API یک پروسه با چند thread اجرا می‌شود تا محدودیت نرخ و شمارش کد پیامکی دقیق بماند؛ برای بار بیشتر `GUNICORN_THREADS` را بالا ببرید، نه تعداد worker.
