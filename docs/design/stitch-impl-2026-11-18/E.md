# Group E — admin dashboard + logistics documents (Stitch faithful rebuild, 2026-11-18)

Branch `redesign/e-admin-logistics` (base 1aa1dba, foundation c55e50b). Evidence: `E/NN-*.png` = `compare.sh` output
(Stitch render left, local page right), captured from `next dev -p 4601` against the backend on :4600 using a copy of
the seeded TEST DB (`/tmp/stack-4600/e2e.db` ← `/tmp/e2e-template.db`).

## How screenshots were authenticated (screenshot tooling only — no app code involved)
A local proxy (`/tmp/eproxy/p.js`, not committed) sat in front of `next dev`:
- strips the CSP header (`next dev` needs `eval`, the site CSP forbids it — same as group B);
- logs in with a TEST account on every HTML request and pre-sets `localStorage.60online_token` (the site's own session key) and
  `60online_theme` (light/dark): admin = seeded `admin@60online.ir`; seller = a screenshot fixture `fixture.seller@test.local`;
- forwards `/api/*` straight to Flask (as nginx does in production). The Next `/api/v1/[...path]` route in this repo is a
  read-only preview proxy that answers POST with `preview_read_only`, so the calculator's `POST /shipping/quote` needs this;
- optional `?__inj=<name>` appends a small script that clicks the document button, fills the calculator destination
  (اصفهان/اصفهان) or attaches a generated grey PNG labelled «TEST IMAGE» for the zoom view (screen 34).
- Seller documents need a shipment. The test DB has none, so `/tmp/efix/fixture.py` (not committed) created, in the DB **copy only**,
  a test seller «فروشگاه آزمایشی», two products «کالای آزمایشی الف/ب», one checkout and one shipment through the real API.

| Screen | Route / component | Status | Notes | Data source |
|---|---|---|---|---|
| 18 داشبورد ادمین (1440) | `/admin` → `components/admin/AdminShell.tsx`, `AdminDashboard.tsx` | MATCH (layout) / PARTIAL (content) | w-64 white sidebar with Material icons + active navy pill, 64px top bar (breadcrumb, theme, notifications, primary CTA), command-centre header with snapshot clock + refresh, 4 KPI cards (icon tile, footer row), 3 bento panels, table card with filter/CTA + footer bar, audit bar — same tokens/spacing/radii. Content is real: KPIs = `personal_today`, `org_waiting` (+`quotes_submitted`), `suppliers_inactive`, `settlements_pending`; panels = Moadian/Sepidar status, my org operations, logistics links + `missing_images`; table = attention queue. Not shown (no backend): GMV + sparkline, fleet on-time %, credit ratings, company orders table, search box. Sidebar keeps all 26 admin sections (Stitch shows 5). | `GET /admin/dashboard` |
| 02 داشبورد ادمین dark | `/admin` (theme=dark) | PARTIAL | Same markup; on this branch `st-*` are static hex colours, so dark mode only flips a few globals (inputs). Becomes dark automatically once group A's `st-*` CSS variables (`html[data-theme=dark]`) are merged. | same |
| 54 محاسبه‌گر وزن و هزینه حمل | `/logistics/estimate` (new) → `components/logistics/ShippingEstimator.tsx` | MATCH (layout) / PARTIAL (features) | Header band with blurs + reference card + reset; 5/7 split: steps ۱–۳ (package dims/weight/flags + qty stepper & chips, origin/destination, strategy + service levels + COD/insurance), weight & CBM KPI tiles, fleet card, tariff breakdown with total box, dark action bar, 4-tile strip. **Costs are real** (the earlier note was wrong: `POST /api/v1/shipping/quote` exists, public, buyer-facing price). Weight/CBM/volumetric are arithmetic on user input. «به‌زودی»: catalog-product mode, multi-destination parts, fleet recommendation, dispatch schedule, «ثبت در پیش‌فاکتور». Stitch claims (72h guarantee, 12 hubs, 20bn insurance, ستاد) replaced by true statements. | `POST /shipping/quote` (active carrier tariffs) |
| 03 حواله خروج انبار و بارنامه A4 | `/sell` → «ارسال سفارش‌ها» → «حوالهٔ خروج و بارنامه» → `WaybillDoc` in `components/seller/ShipmentSheets.tsx` | MATCH (layout) / PARTIAL (fields) | Command strip (breadcrumb, order chip, print/PDF/close), status banner, A4 paper: logo/title/number block, reference bar, 4 party boxes, navy items table, 3-tile totals, notes, 3 signature boxes, Code128 footer. Print = same paper via `PrintSheet` (browser «Save as PDF»). The two old buttons (exit slip, waybill) are merged into this one document, like Stitch. Not in data → left as blanks to fill by hand: warehouse keeper, driver name/plate, seal number, per-item physical state, gross weight with pallet. QR replaced by the real Code128 of the tracking number. | shipment label (`GET /supplier/shipments`) + `GET /supplier/orders/{id}` items |
| 01 برگه تحویل راننده (light) | `/sell` → «نسخهٔ راننده» → `DriverSheet` | MATCH (layout) / PARTIAL | Full-screen mobile sheet: app bar, carrier/status card, barcode card + order strip, receiver card with big call button, address + copy, 3 cargo tiles, checklist, «ثبت مغایرت» row (opens the discrepancy case), fixed bottom status bar. No driver identity/plate/seal/GPS/digital signature in backend → not shown; the bottom bar shows checklist progress instead of «تأیید نهایی». Checklist is page-local (stated on the sheet). | same |
| 04 برگه تحویل راننده dark | same (theme=dark) | PARTIAL | Pending group A's `st-*` dark variables (see 02). | same |
| 31 گزارش مغایرت بارنامه در برابر سفارش (desktop) | `/sell` → «ثبت مغایرت» → `DiscrepancySheet` | MATCH (layout) / PARTIAL | Sticky case header (breadcrumb, case no, waybill, flagged chip, close/PDF/print), right column: case info, physical documents (photo upload), per-item registration with ± stepper + reason + note, dark summary; left column: live A4 «صورت‌جلسهٔ مغایرت» preview (also what prints). Rial loss estimate, QC decision text, inspector/driver identities and stored case number are not in data → omitted; case no. = `DR-<fulfillment order id>`. | same; nothing written to server |
| 37 پرونده مغایرت — اپ سرپرست انبار (mobile) | same component at 390px | MATCH (layout) / PARTIAL | Single column + fixed bottom «مشاهدهٔ صورت‌جلسه و چاپ A4» + «بستن». Driver card / KPI (نرخ مغایرت، تأخیر، رضایت) and QC actions not shown (no data). | same |
| 34 پاپ‌آپ بزرگ‌نمایی (mobile) | same → photo → «مشاهده و بزرگ‌نمایی» | MATCH | Dark full-screen viewer: close, title + tracking, rotate, zoom ± with %, image, «ذخیرهٔ تصویر» + back. Evidence uses a generated «TEST IMAGE» PNG. «ارسال به کارتابل بازرسی» omitted (no backend). | user's own photo (client only) |
| 38 داشبورد تحلیل خطای ناوگان + مودال | `/admin/logistics` (new) → `components/admin/AdminLogistics.tsx` | PARTIAL | Header, 4 KPI cards, trend + root-cause cards, table card in Stitch style. Discrepancy cases are not persisted, so discrepancy %, OTIF, delays, CSAT, trend, donut and the case modal are «به‌زودی» empty states (no sample numbers). The table shows the real carrier tariffs instead of per-vehicle/driver performance (no fleet/driver data). | `GET /admin/carriers/tariffs` |
| 36 گزارش‌های تحلیلی زنجیره تأمین | `/admin/logistics` | PARTIAL | Same page (36 and 38 share layout). AI/alert cards replaced by a «جریان فعلی اسناد لجستیک» card describing what works today. | same |

## Backend / contract notes
- `POST /api/v1/shipping/quote` (public) works with explicit parcels `{length_mm,width_mm,height_mm,gross_weight_g,is_fragile,requires_cold_chain,quantity}`,
  `origin/destination {province, city}`, `service_levels`, `strategy`, `cod_value_minor`, `insurance_value_minor`; returns `price_minor` (Rial; shown in Toman via `formatPrice`).
  The calculator caps quantity at 1000 because the service expands one parcel per unit.
- The Next `app/api/v1/[...path]` route is read-only (POST → 405 `preview_read_only`, except pack-builder). In production nginx sends `/api` to Flask,
  so the calculator works there; in a Next-only preview it shows that error message honestly.
- Needed for full 31/36/37/38: a backend table + API for delivery-discrepancy cases (lines, reason, photo, status) and fleet/driver data; then the analytics can be computed.
- Seller documents still write nothing (as before).

## Shared needs (group A)
- Dark mode for 02/04 depends on A's `st-*` CSS variables. No new icons needed: every icon used is in `icons-included.txt`.
- Admin pages no longer use `.shell/.sidebar/.topbar` from `admin.module.css` (other module classes unchanged).

## Verification
- `npx tsc --noEmit` PASS and `NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js REVIEW_DIST_DIR=/tmp/next-e npx next build` PASS (exit 0; `/admin/logistics` and `/logistics/estimate` built), 2026-11-18. tsconfig.json / next-env.d.ts restored after the build.
- Auth/role gate in `AdminShell` unchanged (loading → login prompt → `role!=="admin"` block). `/admin/logistics` sits under the same layout.
