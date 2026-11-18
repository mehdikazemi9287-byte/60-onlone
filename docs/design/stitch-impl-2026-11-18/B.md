# Group B — catalog / search / product detail (Stitch-faithful rebuild, 2026-11-18)

Branch `redesign/b-catalog-product` (base c55e50b). Evidence: `B/NN-*.png` = `compare.sh` output (Stitch left, local page right),
captured against `next dev` on the seeded TEST DB copy (`/tmp/e2e-template.db`, backend :4300). Because `next dev` needs
`eval` and the site CSP forbids it, screenshots went through a local proxy that only strips the CSP header (and, for the dark
screens, pre-sets `localStorage.60online_theme=dark` — the site's own theme mechanism). No app code was changed for that.

| Screen | Route | Status | Notes | Data source |
|---|---|---|---|---|
| 23 دسته‌بندی و جستجو (desktop 1440) | `/category/[slug]`, `/search` | MATCH (layout) / PARTIAL (content) | Breadcrumb+meta bar, w-80 sidebar (purchase-mode switch, category tree, budget slider, condition checkboxes, brand search list, CTA), sort pills, grid/list switcher, active-filter chips, 3-col cards, numbered pagination, advisory box — all ported. Stitch's per-card perks (logo print, credit sale, tier price «+۲۰ عدد», «تأمین‌کننده رسمی», rating) have no per-product listing data: tier price/perks are not shown; rating only when the API returns one; brand badge replaces «تأمین‌کننده رسمی». Micro-bar claims (Moadian instant invoice, palletised delivery) replaced by true statements. Purchase-mode «سازمانی با فاکتور» links to `/org` (no channel filter in the listing API). | `GET /storefront/products` (group=family, facets, attribute_facets, price_range), `GET /storefront/taxonomy` |
| 14 دسته‌بندی و جستجو (mobile 390) | same routes | MATCH | Search field with clear, chip carousel (filter&sort sheet, sort, «فقط موجود», «خرید آنلاین», sub-categories), count + list/grid switcher, row cards, «نمایش موارد بیشتر» (appends next API page), bottom sheet with sort grid + filters. Stitch's «فاکتور رسمی سازمانی» toggle omitted (no backend filter). The shared mobile header (group A) still shows its own search above. | same |
| 27 دسته‌بندی و کاوش کالا (mobile) | `/category` | MATCH | Search box, right rail of main categories, dark banner, «زیردسته‌ها» header + «مشاهده همه N کالا», 2-col tiles with count badge. Category photos do not exist → Material icon in the tile image area. When a node has no children (current test taxonomy) the tiles show that category's real products (`کالاهای این دسته`). Desktop reuses the same explorer (no desktop Stitch screen). | `/storefront/taxonomy`, `/storefront/products?category=` |
| 05 کاوش دسته‌بندی dark (mobile) | `/category` (theme=dark) | PARTIAL | Dark palette from screen 05 applied via `html[data-theme=dark]` (site toggle). Same markup as 27, so 05's horizontal banner card and filled active-rail tile differ slightly. | same |
| 08 جزئیات کالا (desktop) | `/products/[id]` | MATCH (layout) / PARTIAL (content) | Breadcrumb, chips + title, 520px gallery (zoom, trust badge, 4 thumbs), spec card as tiles, sticky 5/12 buy box: seller header, stock/lead line, variant chips, «انتخاب شیوه خرید» radio cards (retail / org), qty stepper + live total, primary + secondary CTA, assurance lines, consult card. Hidden for lack of data: reviews block, personalization block, satisfaction %, hotline number (links to `/contact`). Added (kept from previous page): description card, full sellers list, Buy Box winner/others, alternatives/related. | `GET /storefront/products/:slug` (+token for org tiers), `/storefront/products/:slug/offers`, `/alert`, cart API, org draft |
| 12 جزئیات کالا (mobile) | `/products/[id]` | MATCH | Full-bleed gallery with counter + dots, title card, purchase-mode card, seller card, spec/description/sellers cards, sticky qty + add-to-cart bar (above the site bottom nav). Review card + accordions not rendered (no data). | same |
| 20 جزئیات کالا dark (desktop) | `/products/[id]` (theme=dark) | MATCH | Dark tokens mapped from screen 20 (bg #0B1418, cards #141D21 + hairline #1F2D35, primary #004E72, text #E8EEF1/#8FA2AD). | same |

## Behaviour kept
Filters/sort/pagination/attribute facets in the URL; family grouping; packs section; empty-state → `/requests/new`; add-to-cart (login redirect),
wishlist, variant links, stock alert, org-draft add with quantity, MOQ/max qty, VAT-inclusive price, unit price, list-price disclosure, sale blocker text,
TEST provenance badge, JSON-LD (unchanged in `page.tsx`).

## Files
- `frontend/src/components/catalog/CatalogBrowser.tsx` (rewritten), `AttributeFilters.tsx` (rewritten: `FilterSidebar`, `FilterSheet`, chips),
  `stitchDark.module.css` (new, scoped dark mapping), `stIcon.ts` (new, Material icon per taxonomy node)
- `frontend/src/components/product/ProductCard.tsx` (Stitch 23 tile + 14 row; `ProductGrid` gains `view`), `BuyBoxOffers.tsx` (restyle)
- `frontend/src/app/category/page.tsx`, `frontend/src/app/products/[id]/ProductDetail.tsx` (rewritten)

## Needs from group A (shared)
- Site-wide dark mapping of `st-*` tokens belongs in `globals.css`; B uses a scoped CSS module until then.
- Icons missing from the subset (wanted): `laptop_mac`, `smartphone`, `router`, `tv`, `kitchen`, `checkroom`, `chair`, `construction`, `pets`,
  `diamond`, `child_care`, `fitness_center`, `egg`, `search_off`. Utility `no-scrollbar` does not exist (used arbitrary variants).
- Mobile header: Stitch 14/27 show a page-level search under a compact app bar; the shared header also renders a search row → two search fields on mobile.

## Verification
- `npx tsc --noEmit` PASS; `NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js REVIEW_DIST_DIR=/tmp/next-b npx next build` PASS (exit 0), 2026-11-18.
- Test DB has no product images, ratings, spec groups or sub-categories, so those states were exercised only through their empty/fallback paths.
