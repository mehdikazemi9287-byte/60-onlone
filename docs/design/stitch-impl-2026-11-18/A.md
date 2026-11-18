# Group A — Home, shared layout, mega menu, theme toggle (Stitch faithful rebuild, 2026-11-18)

Branch `redesign/a-home-layout` (base c55e50b). Evidence: `A/*.png` = Stitch render (left) | local page (right),
captured from `next dev -p 4201` against the backend on :4200 using a copy of the seeded TEST DB (`/tmp/e2e-template.db`).
The test DB has 14 products with no photos, 5 flat categories and **no packs**. So the evidence shows plain empty
photo frames and no pack section. With production data the same components show real photos and packs.

| Screen | Route / component | Status | Notes | Data source |
|---|---|---|---|---|
| 30 خانه (desktop) | `/` → `components/home/HomeSections.tsx` | MATCH (layout) / PARTIAL (copy) | Same section order (hero 7/5 grid + KPI tiles + image card → sticky chips → 3 pack cards → 4-col product grid → 4 value tiles), same st- tokens, spacing, radii, icons and type (Stitch's own font-size inheritance is reproduced). Copy that Stitch states as fact but we cannot back (30-day credit, 7-day guarantee, dedicated fleet, «کاتالوگ ۱۴۰۳») is replaced by real features with links. The barcode-scanner icon is dropped (there is no scanner feature). | products: `GET /storefront/products` (chip → `?category=`); chips: `GET /storefront/taxonomy`; packs: `GET /storefront/packs(+/:slug)`; hero copy/image: content panel block `hero` (`/content/pages/homepage`); hero photo = real catalog image |
| 16 خانه (mobile) | `/` (same component, `md:` breakpoints) + Header | MATCH / PARTIAL | Order: chips → banner → packs (horizontal 290px cards) → 2-col grid → trust banner; 5-tab bottom nav. The location bar «ارسال به تهران… تحویل ۲ ساعته» is hidden (no data). The rating row appears only when a product has real reviews. A menu (drawer) button sits next to the bell so the desktop-only links stay reachable. Mobile has no footer, as in Stitch. | as above; cart badge `GET /cart` |
| Header (30/16) | `components/layout/Header.tsx` | MATCH | Official mark `/brand/60online-mark.png` instead of Stitch's «۶۰» square. The org chip shows only when the user has an active org (`GET /organizations`). The user pill shows the real name; logged-out users see «ورود / ثبت‌نام». A theme pill sits beside the cart (as in screen 22). Nav links → `/packs`, `/business/catalog`, `/requests/new`, `/sell`, `/me/proformas`, `/organization/supply-contracts`. The mobile search row is hidden on `/search` and `/category/*` (those Stitch screens have their own search). | auth context, `/organizations`, `/cart` |
| Footer (30) | `components/layout/Footer.tsx` | PARTIAL | 4-col grid + bottom bar as in Stitch. The trust-badge column (اینماد/ساماندهی/اتحادیه) is replaced by real top categories until official badge data exists. The version label is left out. | taxonomy |
| 15 مگامنو (desktop) | `components/layout/MegaMenu.tsx` | MATCH (structure) | 820px panel, 4/8 split, active-row style, count chips, CTA row. Groups = real sub-categories with their children; a node without children shows «این دسته زیرشاخه ندارد». The CTA goes to `/pack-builder` (a real route) instead of «مشاوره». | `GET /storefront/taxonomy` |
| 22 مگامنو dark | same component + dark tokens | PARTIAL | Same component; colours come from the Stitch dark palette. Screen 22's extra header strip (catalog notice, phone number) and the promo card inside the menu are not shipped (no data). | taxonomy |
| 33 ویجت تم + ترنزیشن دایره‌ای | `components/ui/DashTheme.tsx` + `globals.css` | MATCH (widget) / PARTIAL (page) | Pill as in screen 33: light = white pill with a golden sun knob; dark = petrol pill with a night knob; 350ms slide+rotate. The page switch is a circular reveal from the toggle (View Transitions, 450ms; reduced-motion = instant). Screen 33's showcase/demo page is not built as a route. | localStorage `60online_theme` |

## Shared changes other groups get
- **st- colours are CSS variables** (`tailwind.config.ts` → `rgb(var(--st-…) / <alpha>)`, values in `globals.css`):
  light = screen 30; dark = Stitch dark palette (screens 22/33) under `html[data-theme="dark"]`. Every `*-st-*` class
  now switches with the theme, so no per-group dark CSS module is needed. New tokens: `st-accent-coral`,
  `st-accent-primary`, `st-accent-electric`, `st-hairline-border`, `st-text-primary`, `st-text-secondary`.
  In dark mode, `text-st-primary-container` maps to `st-text-primary`, because the dark value is a fill colour.
  Filled `bg-st-primary-container` buttons should use `text-white`, because `on-primary` is unreadable on it in dark mode.
- `.no-scrollbar` utility; `.st-bottom-nav` styles; `categorySymbol()` (Material Symbols name per category).

## Icons needed (not in the subset)
computer/laptop_mac, smartphone, router, kitchen, checkroom, child_care, chair, construction, fitness_center, pets, diamond.
Until then, category icons fall back to `category` or the nearest icon in the subset.

## Verification
- `npx tsc --noEmit` PASS (2026-11-18).
- `REVIEW_DIST_DIR=/tmp/next-a NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js npx next build` PASS (2026-11-18).
- Visual: the evidence PNGs above (dev server). CSP was bypassed only inside the headless capture tool, because `next dev` uses eval.
- Not run: logged-in states (org chip, user name) and real pack cards. The capture used no test login, and the test DB has no packs.
