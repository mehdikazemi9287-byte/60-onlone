# انتقال فایل به سرور 60online-prod از کنسول وب آروان

گیت‌هاب و pypi.org از سرور در دسترس نیستند، پس `git pull` روی سرور کار نمی‌کند. رجیستری npm در دسترس است.
تغییرات کد با «پچ فشرده‌شده + base64» از کنسول وب (noVNC) تایپ و روی سرور اعمال می‌شود.

## مراحل
1. **روی سیستم توسعه:**
   ```bash
   git diff <کامیت-سرور> origin/main -- . ':!README.md' > x.patch
   gzip -9 -c x.patch | base64 -w0 > x.b64
   sha256sum x.b64
   ```
   - کامیت فعلی کد سرور در README آمده است.
2. **در کنسول آروان:** پنل آروان → ابرک `60online-prod` → دکمهٔ «کنسول».
3. **تعریف تابع تایپ:** در DevTools همان صفحه (یا ابزار JS مرورگر) این تابع را تعریف کنید. کیبورد کنسول کاراکترهای `: | _` را خراب می‌کند، ولی `rfb.sendKey` درست می‌فرستد.
   ```js
   window.__ks=c=>c==='\n'?0xff0d:c.charCodeAt(0);
   window.__slow=async(s,ms=40)=>{window.__progress=0;for(let i=0;i<s.length;i++){rfb.sendKey(window.__ks(s[i]));window.__progress=i+1;await new Promise(r=>setTimeout(r,ms));}window.__done=true;};
   window.__type=(s,ms)=>{window.__done=false;window.__slow(s,ms);return 'started';};
   ```
4. **تایپ فایل:** base64 را در تکه‌های ۶۰۰ کاراکتری تایپ کنید (`echo -n '...' >> /tmp/x.b64`).
   - پیش از تایپ، طول و checksum هر تکه را در مرورگر بسنجید.
   - اگر تب در پس‌زمینه باشد سرعت تایپ کم می‌شود؛ حدود ۱۰ تا ۲۰ کاراکتر در ثانیه.
5. **اعمال روی سرور:**
   ```bash
   sha256sum /tmp/x.b64
   base64 -d /tmp/x.b64 | gunzip > /tmp/x.patch
   cd /opt/60online-new && git apply --check /tmp/x.patch && git apply /tmp/x.patch
   ```
   - sha256 خط اول باید با مقدار مرحلهٔ ۱ یکی باشد.
6. **ساخت فقط فرانت** (بک‌اند دست نمی‌خورد):
   ```bash
   docker compose -f deploy/.compose-sixty.yml up -d --build --no-deps frontend
   ```
   اگر build شکست بخورد، کانتینر قبلی روشن می‌ماند.
7. **بررسی:**
   - `curl -s -o /dev/null -w %{http_code} https://60online.ir/` و صفحه‌های اصلی
   - `docker ps`
   - دیدن صفحه در مرورگر

استقرار روی سرور اصلی فقط با تأیید صریح مدیر انجام می‌شود (AGENTS.md، قاعدهٔ ۱۱).

## نکته‌های تجربه‌شده (۲۰ آبان)
- ابرک `60online-prod` در ناحیهٔ **سیمین** (`ir-thr-si1`) است، نه قیصر. ابرک‌های قیصر و فروغ مال پروژه‌های دیگرند (دست‌بازار و کارن‌سیر)؛ پیش از تایپ، نام میزبان در خط فرمان را ببینید: `root@60online-prod`.
- `rfb.sendKey(keysym)` را **فقط با یک آرگومان** صدا بزنید؛ با آرگومان دوم خطای `code is not defined` می‌دهد.
- سرعت تایپ زیر ۳۵ میلی‌ثانیه برای هر کاراکتر، Shift را در سرور گیر می‌اندازد (حروف بزرگ و عدد به علامت تبدیل می‌شود). رفع: `rfb._keyPress(0xffe1,1); rfb._keyPress(0xffe1,0)` و برای لغو خط: `rfb._keyPress(0xffe3,1); rfb._keyPress(0x63,1); rfb._keyPress(0x63,0); rfb._keyPress(0xffe3,0)`.
