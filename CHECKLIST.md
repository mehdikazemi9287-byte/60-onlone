# چک‌لیست راه‌اندازی وامبی روی vambi.ir

## کارن
- [ ] DNS دامنهٔ `vambi.ir` و `www.vambi.ir` به سرور فرانت
- [ ] گواهی SSL
- [ ] شمارهٔ خط پیامک کاوه‌نگار برای `KAVENEGAR_SENDER` (فقط روی سرور، نه در گیت‌هاب)
- [ ] تصمیم `STOREFRONT_PRICE_VISIBILITY`
- [ ] ادغام PR #12 و بعد PR #19 در 60-onlone

## فنی (قبل از استقرار)
- [ ] `caddy validate` روی `deploy/Caddyfile`
- [ ] `https://vambi.ir` در `CORS_ORIGINS`؛ `vambi.ir,www.vambi.ir` (بدون https) در `VAMBI_HOSTS`
- [ ] `NEXT_PUBLIC_MAIN_SITE=https://60online.ir` هنگام ساخت فرانت؛ `SSO_ALLOW_LOCALHOST` روی سرور تنظیم نشود
- [ ] بکاپ دیتابیس، بعد مهاجرت‌های 0079 تا 0083
- [ ] استقرار (فقط با تأیید کارن)

## بعد از استقرار
- [ ] آزمون ورود مشترک روی دو دامنهٔ واقعی با HTTPS
- [ ] یک پیامک واقعی هشدار
- [ ] `python3 -m scripts.vambi_readiness` قبول: دست‌کم ۵۰ کالا با قیمت معتبر از دو فروشنده
- [ ] شروع اطلاع‌رسانی طبق [docs/COMMS-PLAN.md](docs/COMMS-PLAN.md)
