# کاتالوگ و دسته‌بندی جزءبه‌جزء (فاز ۶)

## مدل داده
- `attribute_definitions` + `attribute_options`: تعریف ویژگی (text/number/integer/boolean/enum/multi_enum/measure/date)، واحد پایه، بازه، الگو.
- `category_attributes`: اتصال ویژگی به دسته. مقدار NULL یعنی «از والد ارث ببر»؛ `inherit=0` یعنی فقط همین دسته. طرح مؤثر = اجداد + خود دسته (نزدیک‌ترین ردیف برنده است).
- `product_attribute_values`: مقدار تایپ‌شده برای هر master_product. عدد/اندازه = **عدد صحیح در هزارم واحد پایه** (۱٫۵ کیلوگرم → `weight_g = 1500000`).
- `units`: `factor_to_canonical` = هزارمِ واحد پایه به ازای یک واحد (kg=1000000، g=1000). ارقام فارسی و «٫» پذیرفته می‌شوند.
- `category_variation_themes`: محورهای تنوع (مثل `volume_ml,pack_count`)؛ نزدیک‌ترین الگو در درخت. `product_families.variation_theme_code` اختیاری.
- `category_listing_policies`: هر فیلد NULL از والد ارث می‌برد (حداقل تصویر، الگوی عنوان، واژه‌های ممنوع، استثنای انصراف، زنجیره سرد/شکستنی/خطرناک، دسته مالیاتی، مهلت مرجوعی، کمیسیون پیشنهادی، الگوی متا).
- `category_external_mappings`: نگاشت ترب/باسلام/دیجی‌کالا/GS1 GPC برای فید؛ کد خالی = هنوز نگاشت نشده.
- `catalog_quality_scores`: کش امتیاز کیفیت.

## API (Blueprint: `catalog_schema`، ماژول `app/api/v1/catalog_schema.py`)
- عمومی: `GET /api/v1/categories/<slug>/schema`، `GET /api/v1/catalog/units`
- فروشنده: `POST /api/v1/supplier/catalog/validate` با `{category_slug, title, brand, images, attributes}` → خطاها، امتیاز ۰ تا ۱۰۰، چک‌لیست فارسی، عنوان پیشنهادی.
- مدیر: `/api/v1/admin/catalog/attributes`، `.../attributes/<id>/options`، `.../options/<id>`، `.../categories/<id>/attributes/<code>`، `/policy`، `/themes/<code>`، `/mappings`، `.../products/<mid>/attributes`، `/quality`، `.../families/<fid>/variation-check`، `POST .../attributes/backfill` (`dry_run`)، `POST .../policies/apply-defaults`.

## جست‌وجوی فیلتردار
`GET /api/v1/storefront/products?category=...&attr.oil_type=sunflower,canola&attr.volume_ml=1l..2l&attr.halal=1&seller_kind=shop&official=1&in_stock=1`
پاسخ قبلی حفظ شده و `attribute_facets` (شمارش تفکیکی؛ فیلتر هر ویژگی در شمارش خودش نادیده گرفته می‌شود) اضافه شده است.
جزئیات محصول: `spec_groups` (جدول مشخصات گروه‌بندی‌شده)، `unit_price` (قیمت هر کیلوگرم/لیتر/عدد)، `seo` (متا، مسیر کانونیکال، BreadcrumbList و Product.additionalProperty).

## دروازه انتشار پیشنهاد
پیش‌فرض فقط هشدار (`catalog_warnings` در پاسخ ایجاد پیشنهاد). با `CATALOG_ENFORCE_REQUIRED=1` ایجاد پیشنهاد برای کالای ناقص با خطای `catalog_required_attributes_missing` رد می‌شود.

## بذر دسته‌ها
مهاجرت `0065_catalog_taxonomy_seed.sql` فقط گره‌های ناموجود را می‌سازد (نام/والد موجود تغییر نمی‌کند).
