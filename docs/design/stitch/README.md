# 60Online — طراحی‌های Google Stitch (انتقال به Figma و GitHub)

- منبع: پروژه‌ی Stitch «60Online Persian Marketplace App» (project id 1782032533748571327)
- مقصد Figma: https://www.figma.com/design/nU3vf0u1urj1ROKyVEzYqU (فایل «60Online — Stitch Designs»)
- مقصد GitHub: همین پوشه (`docs/design/stitch/`) در شاخه‌ی `design/stitch-export-2026-11-16`

## وضعیت (۲۵ آبان ۱۴۰۵ / 2026-11-16)

| مرحله | وضعیت |
|---|---|
| ساخت فایل Figma مقصد | ✅ انجام شد |
| کپی دسته‌ی ۱ (ردیف بالا: دیزاین‌سیستم + ۷ صفحه‌ی موبایل) از Stitch برای Figma | ✅ در کلیپ‌بورد |
| Paste در Figma | ⏳ نیازمند Ctrl+V دستی کاربر (Paste خودکار توسط مرورگر مسدود است) |
| دسته‌های بعدی (Stitch حداکثر ۱۶ صفحه در هر Export) | ⏳ باقی‌مانده |
| خروجی کد HTML/تصاویر (Zip) و قرار دادن در این پوشه | ⏳ باقی‌مانده — Zip باید دانلود و در چت پیوست شود |

## محدودیت‌های فنی کشف‌شده
1. محتوای Stitch داخل iframe جدا (cross-origin) است؛ خواندن مستقیم HTML صفحه‌ها از مرورگر ممکن نیست.
2. Export در Stitch حداکثر ۱۶ صفحه در هر بار است.
3. Paste خودکار در Figma و خواندن کلیپ‌بورد توسط افزونه مسدود است.
4. سرور stitch.googleapis.com از محیط کاری در دسترس نیست.

## گام‌های بعدی
- Paste دسته‌ها در Figma (یک Ctrl+V برای هر دسته).
- دانلود Zip هر دسته از Stitch → پیوست در چت → commit فایل‌های HTML و PNG در `docs/design/stitch/screens/`.
