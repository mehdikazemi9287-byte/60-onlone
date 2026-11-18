# Stitch → code: faithful redesign toolkit (2026-11-18)

Goal: every page looks like its Google Stitch screen (layout, spacing, type, colors, icons, components),
fed only by real API data. "Inspired by" is not acceptable — compare side by side and close the gaps.

## Sources
- Stitch screens: branch `design/stitch-export-2026-11-16`, `docs/design/stitch/screens/NN-*.html` + `manifest.json`
  (local copy: `/tmp/stitch/docs/design/stitch/screens/`, renders: `/tmp/sshots/NN.png`).
- Desktop screens (width 2560 in the manifest) are 1440px CSS; mobile screens (780/822) are 390px CSS.

## Foundation (already on `redesign/stitch-faithful-2026-11-18`)
- **Tokens**: every Stitch token is in `frontend/tailwind.config.ts` with an `st-` prefix:
  colors (`bg-st-surface-container`, `text-st-on-surface-variant`, `bg-st-primary`, `text-st-tertiary-container`…),
  spacing (`px-st-margin-lg`, `gap-st-gutter-md`, `py-st-space-sm`…), font sizes (`text-st-headline-xl`, `text-st-label-md`…).
  Values are exact copies from screen 30 (shared by screens 01–54). Pack-builder screens 55–63 use their own
  palette (brand-blue `#034EA2`, action-navy `#112D46`, accent-orange `#FF7A00`) — keep using what screens 62/63 use.
- **Icons**: `<span className="material-symbols-outlined">icon_name</span>` (add `icon-fill` for FILL 1).
  Self-hosted subset font; included names in `icons-included.txt`. Need another icon? say so in your handoff.
- **Font**: Vazirmatn (already self-hosted). Stitch `font-<token>` family classes are dropped.

## Tools
- `node tools/stitch/port.mjs <screen.html> [css-selector]` → JSX with st- classes (starting point only).
- `node tools/stitch/render.mjs <screen.html> <out.png> <1440|390>` → offline render of a Stitch screen.
- `tools/stitch/local-stack.sh <port-base>` → backend :base + `next start` :base+1 on a copy of the seeded TEST DB.
  For fast iteration use `next dev` instead: `cd frontend && BACKEND_INTERNAL_URL=http://127.0.0.1:<base> npx next dev -p <base+1>`
  after starting only the backend (see script). Only 2 CPUs: avoid repeated full `next build`.
- `tools/stitch/compare.sh <screen.html> <url> <out.png> <1440|390>` → side-by-side evidence (Stitch left, page right).

## Rules (AGENTS.md applies)
1. Real data only. Stitch sample products, prices, people, org names and photos must NOT ship. Bind to the real API;
   where Stitch shows a feature with no backend, build the UI only if it degrades honestly (hidden or «به‌زودی»), never fake numbers.
2. Owner instruction (2026-11-18): redesign ALL pages faithfully to Stitch, including the homepage and pack builder
   (this is the explicit instruction AGENTS.md rules 4–6 require). Keep behavior, routes, auth and API contracts intact.
3. Stay inside your group's files. Shared layout (Header, Footer, MegaMenu, globals.css, tailwind.config.ts) is owned by group A only.
4. Evidence: for each screen you implement, save `docs/design/stitch-impl-2026-11-18/<group>/NN-<name>.png` (compare.sh output)
   at the screen's width, plus a short `<group>.md` table: screen → route → status (MATCH / PARTIAL + why) → data source.
5. `npx tsc --noEmit` must pass. Do not run migrations or touch production. Commit on your branch; do not merge.
