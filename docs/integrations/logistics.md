# لجستیک و استانداردها (فاز 5C)

## داده‌های لجستیکی کالا
- جدول `product_logistics_specs` (برای هر کالا `p:<id>` یا هر پیشنهاد فروشنده `o:<id>`؛ پیشنهاد فروشنده اولویت دارد).
- ابعاد به میلی‌متر، وزن ناخالص به گرم، پرچم‌های شکستنی/فاسدشدنی/زنجیره سرد، کلاس کالای خطرناک (۱ تا ۹)، کد HS (۶/۸/۱۰ رقم)، ایران‌کد (۱۶ رقم) و GTIN-8/12/13/14 با رقم کنترلی GS1.
- وزن حجمی: `طول×عرض×ارتفاع (mm) ÷ ضریب` به گرم (پیش‌فرض ۵۰۰۰، برای هر تعرفه قابل تنظیم). وزن قابل محاسبه = بیشینه وزن واقعی و حجمی، گردشده به گام وزنی تعرفه.
- سرویس: `app/services/product_standards_service.py`.

## استعلام و انتخاب حامل
- `shipping_rate_service.quote_shipping(conn, origin, destination, parcels, ...)` همه حامل‌های فعال `logistics_carriers` (تیپاکس، چاپار، پست پیشتاز، الوپیک فقط درون‌شهری) را با سطوح `same_day`/`express`/`economy` قیمت می‌دهد.
- حامل دارای API زنده از طریق `live_quoter` تزریقی پرسیده می‌شود؛ در نبود یا خطا، تعرفه محلی (`carrier_tariffs` + ماتریس استانی `carrier_tariff_zones` با `*` و `=` برای درون‌استانی + `logistics_remote_areas`) استفاده می‌شود.
- هزینه‌ها: پایه + هر کیلو + مناطق دورافتاده + شکستنی + کارمزد پرداخت در محل + بیمه؛ همه با ریال صحیح. قیمت خریدار = هزینه + `markup_bps`.
- راهبرد `cheapest` یا `fastest`؛ استعلام منتخب در `shipping_quotes` و روی `shipment_plans.selected_quote_id` ذخیره می‌شود.
- تعرفه‌های اولیه مهاجرت نمونه‌اند و باید با نرخ واقعی از پنل ادمین جایگزین شوند.

## مرسوله چندفروشنده‌ای
- `shipment_orchestrator.create_shipment_for_fo` برای هر سفارش تأمین یک مرسوله با برچسب (فرستنده/گیرنده، شماره رهگیری = بارکد، Code128-B) می‌سازد؛ تکرار درخواست همان مرسوله را برمی‌گرداند.
- SLA: مهلت ارسال از زمان آماده‌سازی فروشنده (`lead_time_days`) و مهلت تحویل از SLA حامل، با حذف جمعه‌ها. اگر `promised_prep_at` خالی باشد مهلت ارسال در آن نوشته می‌شود.
- وضعیت‌های نرمال: created, picked_up, in_transit, out_for_delivery, delivered, failed, returned. نگاشت کدهای هر حامل در `TRACKING_STATUS_MAP` آداپتورها (موقت، تا تأیید مستندات رسمی) و قابل بازنویسی با `logistics_carriers.status_map_json`.
- وب‌هوک رهگیری: `registry.get_tracking_event_handler()` → `apply_tracking_event(conn, carrier, payload)` با کلیدهای `tracking_number`, `status`, `event_id`, `occurred_at`, `location`. رویداد تکراری بی‌اثر است و وضعیت عقب‌گرد نمی‌کند. «تحویل‌گرفته از فروشنده» سفارش را `dispatched` و «تحویل شد» آن را از طریق `fulfillment_service.supplier_mark_delivered` تحویل‌شده می‌کند (ثبت بدهی به فروشنده).
- مرجوعی: `create_return_shipments` برای درخواست تأییدشده، مرسوله برگشتی از مشتری به فروشنده می‌سازد.

## API (`app/api/v1/logistics_v2.py`، بلوپرینت `logistics_v2`)
| مسیر | دسترسی |
|---|---|
| `POST /api/v1/shipping/quote` | عمومی، بدون هزینه داخلی |
| `GET/POST /api/v1/supplier/shipments`، `POST .../<id>/pickup` | فروشنده، فقط سفارش‌های خودش |
| `GET/POST /api/v1/admin/carriers/tariffs`، `PUT/DELETE .../<id>` | ادمین |
| `GET /api/v1/me/orders/<id>/tracking` | مشتری صاحب سفارش |
