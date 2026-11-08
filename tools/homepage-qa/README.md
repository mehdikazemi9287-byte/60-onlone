# بررسی چشمی صفحهٔ اول بدون نصب پروژه

این ابزار فقط برای بررسی ظاهر `HomeSections.tsx` است و هیچ‌وقت وارد سایت نمی‌شود.
دادهٔ داخل `stubs/api.ts` آزمایشی و محلی است و فقط از نام‌ها و عکس‌های واقعی کاتالوگ استفاده می‌کند.

## پیش‌نیازها
- Node، esbuild، react 19، tailwindcss 4 (کامپایلر) و playwright با Chromium
- در محیط Claude این‌ها در `/opt/npm-tools/node_modules` نصب‌اند.
- فونت وزیرمتن در این محیط نیست و صفحه با DejaVu رندر می‌شود. آیکون‌ها هم مربع جایگزین‌اند.

## اجرا
```bash
cd tools/homepage-qa
mkdir -p images/catalog && cp ../../frontend/public/images/catalog/* images/catalog/
S=$PWD/stubs; F=$(cd ../.. && pwd)/frontend/src/components/home/HomeSections.tsx
esbuild entry.tsx --bundle --outfile=app.js --jsx=automatic --define:process.env.NODE_ENV='"production"' \
  --alias:@/components/home/HomeSections=$F --alias:next/link=$S/link.tsx --alias:lucide-react=$S/lucide.tsx \
  --alias:@/lib/api=$S/api.ts --alias:@/lib/imageQuality=$S/misc.tsx --alias:@/lib/storefront=$S/misc.tsx \
  --alias:@/components/packs/PackCard=$S/misc.tsx --alias:@/lib/utils=$S/misc.tsx --alias:@/lib/content-types=$S/misc.tsx
node tw.mjs "$F"     # app.css
node shot.js         # desk.png و mob.png؛ خطاهای اجرا و اسکرول افقی را چاپ می‌کند
```

خروجی این ابزار جای `npm run build` را نمی‌گیرد. build واقعی روی سرور اجرا می‌شود.
