# «ویترین سازمانی گرم» — visual concept (2026-11-18)

Branch `redesign/g-visual-concept` (base 381332e = integrated Stitch rebuild A–D).

Owner feedback: «فقط یه خورده جمع و جور و شکل و قیافه دار شیک باشه… اینجوری سفید و آبی ول نکنه… چیدمانش قشنگ نیست.»
Answer: keep every Stitch section, component, route and data binding; change the **visual system and composition**:
a warm canvas, a navy “body”, orange accents, tinted bands between sections, a denser grid and a primary action that is always reachable.
Presentation only — no API call, data, auth/role check or money calculation changed. No sample products/prices/photos added.

## Evidence (left = before at 381332e, right = after)
Captured from `next dev` (:4801) against the seeded TEST DB copy (`/tmp/e2e-template.db`, backend :4800). The test DB has
no product photos and no packs, so empty photo frames and the missing pack band are data, not design. Logged-in pages use
test users `alice@parsco.ir` (employee) and `hr@parsco.ir` (organization_admin); the CSP was bypassed only inside the
headless capture tool (`next dev` uses eval). Desktop pairs are downscaled 50%.

| File | Page | Width |
|---|---|---|
| `home-desktop.png` | `/` | 1440 |
| `home-mobile.png` | `/` | 390 |
| `category-desktop.png` | `/category/laptop` | 1440 |
| `product-desktop.png` | `/products/appliance-kettle-2l` | 1440 |
| `cart-mobile.png` | `/cart` (2 test items) | 390 |
| `checkout-desktop.png` / `checkout-mobile.png` | `/checkout` | 1440 / 390 |
| `account-mobile.png` | `/account` | 390 |
| `org-desktop.png` | `/org` (organization_admin) | 1440 |
| `home-desktop-dark-after.png` | `/` dark theme, after only | 1440 (50%) |

## Tokens (`frontend/src/app/globals.css` + `frontend/tailwind.config.ts`)
All `st-*` colours are CSS variables, so every page that uses them changed automatically (including groups E/F at merge).

| Role | Light | Dark (navy-based) | Classes |
|---|---|---|---|
| action-navy (headers, hero, dark panels, headings) | `#112D46` | `rgb(14 34 56)` panels | `bg-st-navy`, `text-st-primary`, `bg-st-primary(-container)` |
| brand-blue (buttons, links, active) | `#034EA2` | `#6EA8FF` | `bg-st-secondary`, `text-st-secondary`, `bg-st-brand` |
| accent-orange (badges, discounts, key numbers, accent bar) | `#FF7A00` | `#FF8A1F` | `bg-st-accent`, `bg-st-tertiary-container` |
| canvas (page) | `#F6F5F1` warm off-white | `#091421` | `bg-st-background`, `bg-st-canvas` |
| card | `#FFFFFF` + hairline `#E8E4DB` + soft layered navy shadow | `#112133` + hairline ring | `bg-st-surface-container-lowest`, `shadow-st-card`, `shadow-st-raise` |
| bands | mint `#EDF3EE`, sand `#F4EEE6`, info `#E7F0FB` | dark tints | `bg-st-mint`, `bg-st-sand`, `bg-st-info` (+ `text-st-mint-ink`, `text-st-sand-ink`) |
| text on navy | white / `#B0C4D8` | — | `text-white`, `text-st-on-navy-muted` |

Other global changes: container `max-w-[1280px]` with 16/24/32px gutters (was 1440 + 64px); radius `rounded-2xl` = 16px,
`rounded-3xl` = 20px; `.bg-st-surface-container-lowest.shadow-sm` cards get the layered card shadow; brand-blue focus ring;
bottom nav active = brand-blue filled icon, orange cart badge. The old scoped dark overrides of groups B/C/D
(`stitchDark.module.css`, `organization/stitch.module.css`) were removed so dark mode follows the site tokens.

## Primitives (`frontend/src/components/ui/st/index.tsx`)
`ST_W` (container), `ST_CARD`, `StIcon`, `IconTile` (coloured icon squares; tones navy/brand/accent/mint/sand/info),
`TONE_CYCLE`, `Band` (tinted full-width wrapper), `SectionHeader` (orange accent bar + eyebrow + title + «مشاهده همه» pill),
`Section` (container + header, optional band), `StatChip` (hero/summary chips, `onNavy` variant), `PageHeader`
(breadcrumb + icon + title on a sand band), `EmptyState` (always offers the next action), `StepBar` (checkout steps).

## Per page
- **Header/footer**: white action row (warm search pill, navy account pill, orange cart badge) + navy navigation strip with an
  orange «دسته‌بندی کالاها» pill and a «پک‌ساز» shortcut; navy footer with accent-bar column titles.
- **Home**: navy hero panel (same copy/links/content-panel fields) with the real catalog image card and three stat chips;
  categories as coloured icon tiles (still filter the grid below); packs on a sand band; product grid 5 columns desktop /
  2 mobile with compact cards; value strip as a compact icon row on a mint band; empty category → guiding empty state.
- **Category/search**: sand page header (breadcrumb, icon tile, title, orange count, trust chips); sticky compact sort bar;
  4-column grid; narrower 14px filter sidebar; navy bulk-order card with orange CTA; info band for org buying; empty state with CTA.
- **Product**: sand breadcrumb band; tighter gallery; sticky buy box opens with a navy “قیمت هر عدد” header (the existing
  VAT-inclusive line unit price); brand-blue primary CTA, orange quote button.
- **Cart**: 3-step bar, accent title bar + orange count, mint free-shipping banner, navy total; the mobile fixed CTA no longer
  overflows the screen (it used to be clipped); guiding empty state.
- **Checkout**: navy step indicator (done = blue, current = orange), icon-tiled section cards, navy payable box, brand-blue CTA.
- **Account**: navy profile panel, accent section titles, coloured quick-action and settings tiles, orders empty state with «شروع خرید».
- **Org panel**: navy sidebar (white active pill), navy welcome panel with orange primary action, KPI cards with toned icon
  tiles and a gradient top edge, compact 15px base.

## Verification
- `npx tsc --noEmit` PASS; `NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js REVIEW_DIST_DIR=/tmp/next-g npx next build` — see the final commit/report.
- Not covered: pages of groups E (admin/operations/logistics) and F (pack builder/packs) were not edited; they inherit the
  new tokens at merge and should be re-checked then. Pages with real photos/packs were not seen (test DB has none).
