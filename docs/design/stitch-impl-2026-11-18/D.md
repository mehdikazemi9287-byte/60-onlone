# Group D — organization side: Stitch → code (2026-11-18)

Branch `redesign/d-org` (base c55e50b). Evidence PNGs in `D/` are side-by-side: Stitch render (left) | local page (right).

**How the screenshots were taken:** backend from `tools/stitch/local-stack.sh` env on port 4500, using a copy of the
seeded TEST DB (`/tmp/e2e-template.db` → `/tmp/stack-4500/e2e.db`); frontend `next dev -p 4501`
(`BACKEND_INTERNAL_URL=http://127.0.0.1:4500`). Logged-in pages were shot with Playwright + system Chrome: login via
`POST /api/v1/auth/login` (test users from `backend/scripts/seed.py`: `hr@parsco.ir` = organization_admin,
`alice@parsco.ir` = employee), token written to `localStorage["60online_token"]`, dark mode via
`localStorage["60online_theme"]="dark"`; `bypassCSP` was needed only because the site CSP blocks `next dev`'s eval.
The test copy got extra **synthetic fixtures, all labeled `(TEST)` / `PO-TEST-*`**: 1 credit contract (admin API),
3 recurring lists, 1 proforma, 3 approved purchase requests → 2 org orders. Nothing touched any real DB.

| Screen | Route | Status | Why / gaps | Data source |
|---|---|---|---|---|
| 26 پنل سازمانی (desktop) | `/org` | MATCH (layout) / PARTIAL | Sidebar, top bar, greeting, 4 KPI cards, orders table with status tabs + search, recurring widget with live pause/resume switches, support card all follow Stitch. Site Header/Footer (group A, root layout) still wrap the panel, so the panel sits below the site header instead of full-height. «صرفه‌جویی تدارکات» KPI and the named account manager have no backend → «به‌زودی» / generic support links. Fleet tracking icon → `/organization/delivery`. Sidebar has the 5 Stitch items + collapsible «بخش‌های بیشتر» with every other existing org route. | `GET /organizations`, `/orgs/{id}/credit-contract` (admin/finance only), `/orgs/{id}/orders` + `/orders/{oid}`, fallback `/orgs/{id}/procurement/requests` for employees, `/me/recurring` (+pause/resume) |
| 21 پنل سازمانی dark | `/org` (theme toggle) | MATCH | Screen-21 palette (#0B1418/#111D23/#1F2D35/#E8EEF1/#8FA2AD/#004E72/#FF6D41) mapped onto the st- tokens inside the panel only (`stitch.module.css`). | same as 26 |
| 25 قراردادهای تأمین دوره‌ای | `/organization/supply-contracts` | MATCH / PARTIAL | Banner, 3 KPI cards, contract cards (frequency + status chips, code, next date, item chips, pause/resume/cancel, quote preview, ready-run). «تخفیف تیراژ / صرفه‌جویی» KPI replaced by the real organization credit contract; «ویرایش اقلام» not shown (no edit endpoint); «ناوگان» timing not shown (no data). | `/me/recurring` (caller-owned lists filtered by org), `/me/recurring/{id}/quote|pause|resume|cancel|runs`, `/orgs/{id}/credit-contract` |
| 19 قراردادها با فیلتر پیشرفته و خروجی اکسل | same route | MATCH | Toolbar: Jalali date range, frequency segmented control, status pills, «خروجی اکسل» (UTF-8 BOM CSV built in browser). | same |
| 32 پیش‌نویس قرارداد تأمین دوره‌ای (A4) | supply-contracts → «پیش‌نویس قرارداد A4» | MATCH | Full-screen viewer with toolbar + A4 sheet: header, legal warning, parties grid, items table with real periodic discount %, totals, two signature boxes. Print via shared `PrintSheet` portal (white A4). VAT line omitted (quote API returns payable only; noted on sheet). | recurring list + live quote + org + credit contract |
| 10 پیش‌نویس قرارداد A4 با مهر و امضا | same viewer | MATCH / PARTIAL | Right-side stamp & signature panel; images stay in memory as data: URLs (never uploaded). Stitch's «تنظیم شفافیت و زاویه» and auto verification code are not implemented (no backend / would imply legal verification). Evidence uses synthetic TEST stamp/sign PNGs. | as 32 |
| 06 خروجی تجمیعی پیش‌فاکتورهای رسمی | `/me/proformas` | MATCH / PARTIAL | Header with counts and selected-sum, live batch progress card, action bar (select page, ZIP, «چاپ تجمیعی A4», Moadian send disabled «به‌زودی»), search + Jalali range + «۳۰ روز اخیر», status tabs with counts, table, pagination, 3 info cards. Stitch's multi-organization admin view does not apply: this is the caller's own proformas (owner-scoped API). | `GET /me/proformas`, `/me/proformas/{n}` |
| 28 پیش‌فاکتور رسمی dark (mobile) | `/me/proformas/{number}` | MATCH / PARTIAL | Top bar, status banner, hero, buyer card, stacked item cards, financial summary + amount in words, sticky pay/PDF/share bar. Buyer legal ids/address/contact are not in the proforma snapshot → not shown. | `GET /me/proformas/{n}` |
| 53 برگه رسمی استعلام بها و پیش‌فاکتور A4 | `/me/proformas/{number}` → «دریافت PDF» (also `?print=1`) | PARTIAL | A4 sheet follows 53 (header, barcode, meta row, seller/buyer cards, items, amount in words, navy total box, terms, signature boxes). Setad (ستاد) branding/fields, QR verification and seller legal ids are NOT printed — no backend; Code128 of the real number instead. Evidence shows the print-media render. | `GET /me/proformas/{n}` |
| 13 پیش‌نمایش صورتحساب مودیان | `/organization/b2b-orders` → فاکتور → «پیش‌نمایش صورتحساب مودیان» | MATCH (UI) | Modal per Stitch: header + pattern chip, meta grid, seller/buyer, items with VAT rate, totals, legal box, actions. **UI only**: tax id «صادر نشده», status «پیش‌نمایش — به کارپوشه ارسال نشده», XML/send disabled «به‌زودی»; the legal box states it is not an official e-invoice. Print uses the existing global `.moadian-modal` print rules. | `GET /orgs/{id}/orders/{oid}/invoice` |
| 52 سفارش عمده سازمانی (desktop) | `/business` (no bulk-order route exists) | PARTIAL | Mapped to the closest real flow: B2B account / bulk inquiry form (`POST /b2b/applications`), restyled as Stitch's side inquiry card; hero, 4-step strip, feature strip, payment methods. Cultural/school pack cards, volume-tier table and Setad number field are omitted (no catalog/pricing/integration in backend); Setad shown as «به‌زودی». | `POST /b2b/applications` |
| 42 سفارش عمده سازمانی (mobile) | `/business` at 390px | PARTIAL | Same as 52 (responsive). | same |

Role checks: server-enforced endpoints unchanged. UI shows credit amounts only for organization_admin/finance;
employees get their own purchase requests instead of org orders (see `D/26-org-panel-employee-role.png`).
`/operations` (other group) keeps the old `PanelShell`; `/org` and `/organization/*` now use `OrgShell`.

Needs for other groups / backend:
- Group A: a way for panel routes to opt out of the site Header/Footer (Stitch org screens are full-height app shells).
- Icons used but not in the subset: none (substituted `work_history`→`apartment`, `barcode`→`qr_code_2`).
- Backend (not done): procurement-savings report, dedicated account manager, recurring-list item edit, Moadian signing/XML/submit, seller legal profile for invoices, Setad integration, bulk pack catalog/volume tiers.
