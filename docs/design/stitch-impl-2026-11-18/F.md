# Group F — Pack Builder: Stitch → code (2026-11-18)

Branch `redesign/f-packbuilder` (base `1aa1dba`, foundation). Owner instruction (2026-11-18): the pack-builder LOOK must match
Stitch 62 (desktop 1440) / 63 (mobile 390), with the full CONTENT of 55, popup 60, flipbook 58 and archive + send form 57/59.
This is the explicit instruction AGENTS.md rules 5–6 require. `PackBuilderInteractive.tsx` (protected editor/quote step) and
`PackCard.tsx` (`UI` used by the protected homepage) were NOT changed.

Evidence PNGs in `F/` are side-by-side (Stitch render left | local page right), captured with Playwright + system Chrome
(`bypassCSP` only for the screenshot, because the site CSP blocks `next dev` eval) against `next dev -p 4701` +
backend :4700 on a copy of the seeded TEST DB (`/tmp/stack-4700/e2e.db`).

**Test data:** the seeded DB has no packs and only `provenance='test'` products. The admin API (`POST /admin/packs`) correctly
refuses them («فقط کالای واقعی…»), so 4 synthetic packs were inserted directly into the temporary DB copy only, with
`provenance='test'` and titles prefixed `(TEST)` (script kept outside the repo). No real DB was touched. The test products have
no photos, so every card shows the honest "no verified photo" placeholder — with real packs the cards show the pack's own
quality-gated item photos.

| Screen | Route | Status | Why / gaps | Data source |
|---|---|---|---|---|
| 62 پک‌ساز (desktop 1440) | `/pack-builder` | MATCH | Same order and shapes: 4-step stepper card, mint hero (badge, title, copy, 60AI input + navy button), 3 method cards with «روش پیشنهادی» badge and blue active border, pill filter bar with count, intro + sort row, 3-col cards (4:3 media, orange corner badge, gray meta chips, item list, «ارزش محاسباتی», navy + outlined buttons), sticky «پیش‌نمایش سبد پک سازمانی» (stepper, mint tier box, selected items, total, CTAs, consult row, trust note), tabbed services card. Content made honest: orange badge = pack tier/kind (no invented «تخفیف تیراژ»), tier box says discounts come with the quote, checklist = the pack's real items (not free logo/shrink perks), hotline → `/contact` (no public number in repo), PDF print disabled «به‌زودی». | `GET /storefront/packs` + `/storefront/packs/{slug}` (via `loadPackDetails`) |
| 63 پک‌ساز (mobile 390) | `/pack-builder` | MATCH | Hero with collapsible 60AI drawer (occasion select + head count → Budget Builder), line stepper, 3 compact method cards, catalog card, chip filters, 16:10 cards with badge + `PK-id` code chip, min-qty chip, item tags, gray price/packaging strip, two buttons, accordions, sticky inquiry bar above the site bottom nav. Catalog card opens the online flipbook instead of a PDF (no PDF exists). The site's own header/bottom nav (group A) replace Stitch's app bar/tab bar. | same |
| 55 پک‌ساز content (desktop) | `/pack-builder` | PARTIAL | 55's blocks are present in the 62 look: occasion filters incl. خیریه, Setad section, logistics, CSR/charity, sidebar summary. 55's «استعلام سریع در ۳ دقیقه» callback form and sample packs not built (no lead/callback endpoint; sample data forbidden). | same |
| 60 پاپ‌آپ شخصی‌سازی | `/pack-builder` → «مشاهده و شخصی‌سازی» | MATCH (UI) | Header (icon tile, title, `PK-id`, orange badge, close), blue info strip with item count, bordered item rows (checkbox, image/icon tile, qty stepper, same-type alternative select from backend, «حذف قلم» / «+ افزودن به پک»), dashed «add more» (opens the real editor), gray right panel: packaging (pack's real `packaging_fa`; other boxes «به‌زودی»), logo print disabled «به‌زودی», count presets + input, mint summary (real weight, pricing basis, total only for an untouched priced pack), apply → editor/quote, link to full pack page, reset. | pack detail (items, `alternatives`, `unit_price_minor`) |
| 58 کاتالوگ ورق‌زدنی | `/pack-builder` → «کاتالوگ ورق‌زدنی» (desktop sort row, mobile catalog card / sticky bar), `/pack-builder/catalog` | MATCH (UI) | Each spread = one real pack: photo page + detail page (items + qty, kind/brands/min chips, price box, «افزودن این پک به پک‌ساز هوشمند», bookmark = add to compare). Zoom, fullscreen, arrows/keys, slider, page counter work. «دانلود نسخه کامل PDF» disabled «به‌زودی»; share uses the real `/packs/{slug}` URL; «ارسال به مسئول خرید» is a `mailto:` with that URL. | same |
| 57 آرشیو کاتالوگ + فرم ارسال (desktop) | `/pack-builder/catalog` (new) | PARTIAL | Hero, search, occasion chips, catalog cards (gradient title overlay, page/item counts, preview + PDF), auto-send form, 4 trust tiles. No catalog archive backend: each card is a LIVE catalog of the current published packs of one occasion group; past years «به‌زودی»; PDF disabled; send form fully disabled «به‌زودی» (collects/stores nothing); trust tiles rewritten to verifiable statements. | `loadPackDetails` |
| 59 آرشیو کاتالوگ (mobile) | `/pack-builder/catalog` at 390 | MATCH (layout) / PARTIAL (features) | App-bar row, inline catalog viewer (prev/next, progress, item chips, min qty, add-to-builder), send card with WhatsApp/e-mail switch (disabled «به‌زودی»), archive rows (PDF disabled, view → flipbook), consult banner → `/contact`. | same |
| `/packs/[slug]` stepper | `/packs/{slug}` | MATCH (stepper only) | Shares `Steps`; rest of the pack page unchanged (out of scope). | `/storefront/packs/{slug}` |

## Behaviour kept
Draft/pending/saved-draft logic, `?pack=`, `?mode=`, `?group=` (+ old aliases), Budget Builder + 60AI intent parsing, compare
(now via flipbook bookmark → «مقایسه N پک»), customize → editor, select → summary → editor/quote (count now parsed with
`positiveInteger`, so Persian digits work), `/account/packs` link. Editor/review/quote = unchanged `PackBuilderInteractive`
(`F/editor-step2-after-select.png`).

## Files
- Rewritten: `frontend/src/components/packs/{PackStudio,StudioHero,PackGridCard,PackSummaryPanel,ProcurementServices,PackCustomizeDialog}.tsx`
- New: `CatalogFlipbook.tsx`, `CatalogArchive.tsx`, `pack-groups.ts`, `frontend/src/app/pack-builder/catalog/page.tsx`
- `studio-ui.ts` → `studio-ui.tsx` (62/63 palette constants, `Icon`, `Soon`); `BudgetBuilder.tsx`: `OCCASIONS` exported only.
- No edits to tailwind.config.ts, globals.css, layout, homepage, `PackBuilderInteractive.tsx`, `PackCard.tsx`.

## Icons
All used icons are in the subset. Stitch 63's `discount` is missing → `local_offer` used (add `discount` if wanted).

## Backend gaps (not done)
Catalog PDF generation/archive by season, automatic catalog send (e-mail/WhatsApp), Setad integration, logistics (CBM/fleet)
estimate, charity delivery, packaging choice / logo upload, tier-discount data per pack, public procurement hotline, callback form.
Also: admin pack API cannot build packs from `provenance='test'` products, so QA fixtures need direct temp-DB inserts.

## Verification (2026-11-18)
- `npx tsc --noEmit` PASS.
- Backend `tests.test_pack_builder_occasions` (all `test_*`) PASS.
- `NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js REVIEW_DIST_DIR=/tmp/next-f npx next build` PASS (exit 0; `/pack-builder`, `/pack-builder/catalog` static). `tsconfig.json`/`next-env.d.ts` restored, `frontend/tmp` removed.
- Visual checks: screenshots in `F/` (desktop 1440 / mobile 390), popup, flipbook, select → editor flow.
