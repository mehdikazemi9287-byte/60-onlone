# Group C — cart / checkout / account (Stitch-faithful rebuild, 2026-11-18)

Branch `redesign/c-cart-checkout` (base 1aa1dba). Evidence `C/NN-*.png` = `tools/stitch/compare.sh` output (Stitch left, local page right)
unless noted. Captured against `next dev` on a copy of the seeded TEST DB (`/tmp/e2e-template.db`, backend :4400, user `alice@parsco.ir`,
synthetic `provenance='test'` products). Screenshots went through a local screenshot-only proxy (not in the repo) that strips the CSP header
(`next dev` needs `eval`), pre-sets `localStorage` (test token; `60online_theme=dark` for the dark screen) and sends `/api/v1/*` straight to
the TEST backend, because the Next `/api/v1` route is a read-only preview proxy (POST → 405). No app code was changed for that.

| Screen | Route | Status | Notes | Data source |
|---|---|---|---|---|
| 11 سبد خرید (mobile 390) | `/cart` | MATCH (layout) / PARTIAL (content) | Free-shipping banner (only when server shipping fee = 0), title + count chip + «خالی کردن سبد», item cards (96px thumb, title, ×, unit price, stepper `+ n −`, «مجموع ردیف»), coupon card, «خلاصه» card with highlighted total, 2 trust tiles, fixed CTA bar above the site bottom nav. Not shown (no per-line data): org/discount badges, customization row, «سود سازمان», strike-through list price, B2B discount line. Coupon field is disabled with «به‌زودی» (no coupon endpoint for the online cart). VAT line says «در تسویه‌حساب» (cart API has no tax). SKU replaces Stitch's origin sub-line. Trust tiles state true facts (72h proforma, 7-day withdrawal). | `GET/PATCH/DELETE /cart`, `/cart/items/:id`, `POST /me/proformas` |
| — سبد خرید desktop (no Stitch screen) | `/cart` | n/a (`C/11-cart-desktop.png`, page only) | Same cards in screen 24's 8/4 grid, sticky summary with inline CTA. | same |
| 24 تسویه حساب (desktop 1440) | `/checkout` | MATCH (layout) / PARTIAL (content) | Stepper card (3 steps; step 2 → done when the address is confirmed), address card (typed form → collapses to Stitch's summary row with «تغییر یا ویرایش»), delivery card, B2B invoice card with toggle, payment card with radio rows, sticky 4/12 summary (item list, rows, payable, CTA pill, trust lines) + help box. Delivery: one honest option (seller delivery, server shipping fee, max `lead_time_days` when present) — no time-slot backend, chip «انتخاب بازه زمانی: به‌زودی». Invoice: toggle rendered disabled «(به‌زودی)» — checkout has no legal-entity invoice field; shows buyer org, VAT rate, link to proforma; shows `?proforma=` number when paying a proforma. Payment rows = only what the server offers: org credit + split (when `has_organization_credit`) and each `/checkout/payment-options` provider (card / external credit). `C/24-checkout-desktop-address-confirmed.png` shows the collapsed address + active step 3. | `GET /cart`, `GET /checkout/quote`, `/checkout/payment-options`, `/checkout/welfare`, `/legal/terms`, `POST /checkout` |
| 29 تسویه حساب (mobile 390) | `/checkout` | MATCH (layout) / PARTIAL (content) | Compact stepper with icons, org notice pill, section titles above white cards, option cards with filled-radio + tinted selected state, breakdown card, fixed bottom bar (payable + «ثبت سفارش نهایی») above the site bottom nav. Same content limits as 24. `C/29-checkout-mobile-address-confirmed.png`; `C/29-checkout-mobile-order-placed.png` = real mock-card order placed through this UI. | same |
| 09 تسویه حساب dark (desktop) | `/checkout` (theme=dark) | MATCH | Scoped dark mapping (`components/checkout/stitchDark.module.css`, same palette as group B + `lg:` variants used by the responsive cards). | same |
| 17 حساب کاربری (mobile 390) | `/account` | MATCH (layout) / PARTIAL (content) | Profile card (initials avatar, verified badge only with an org membership, role/org pill, email), balance carousel, orders card with status tabs + latest order mini-card + progress by real status, 2×2 quick actions, settings list, logout. Balances: welfare wallet (only when available), org credit (`/me/credit`, dark card), 60Coin (`/me/loyalty`). Not rendered (no backend): cash wallet/top-up, phone number, profile edit, saved addresses, app version, delivery-time line. «مرجوعی» tab omitted (returns are per order, not in the list). Quick actions point to real routes (`/account/packs`, `/me/proformas`, `/requests`, `/me/recurring`); list rows to `/org`, `/contact`, `/notifications`, `/60club`, `/benefits` (+ supplier/admin panels by role). Counts come from the first 50 orders. | `/me/credit`, `/checkout/welfare`, `/me/loyalty`, `GET /orders?page_size=50`, `/me/org-invitations` |

## Behaviour kept (checkout = presentation only)
Same `checkout.place(...)` call and arguments; idempotency key per attempt, renewed only after a definitive (status≠0) rejection; buyer-terms
checkbox gates the CTA; welfare opt-in; external provider sent only when a non-card provider is chosen; `?proforma=` pass-through;
`payment_redirect` → `goToPaymentGateway` (unchanged; bank / provider redirect); `payment_gateway_unavailable` → purchase-request fallback with its own
idempotency key; `?payment=failed&reason=` notices; login redirect `/login?next=/checkout`; empty-cart and load-error states. Payable shown =
`cash_due` (− welfare share), as before. Cart: qty/remove/clear with server refetch on rejection, over-stock warning blocks checkout, proforma,
60AI link, `/login?next=/cart`.

Deliberate presentation differences (no request change):
- Address, payment and confirm are one page (Stitch has no separate steps). The CTA additionally stays disabled until the 5 required address
  fields are filled (previously the «ادامه» button enforced the same rule).
- The org-credit row is shown whenever the server quote uses credit (`credit_to_use_minor > 0`), not only for credit/split: the server applies
  credit regardless of the chosen method (`checkout_service` uses the method-agnostic quote), so the old card view hid a deduction it showed in
  the payable. A «جمع کل سفارش» row (`final_payable_minor`) was added.
- Choosing credit/split clears a previously chosen external provider (before, its radios were hidden but the state could survive).

## Files
- `frontend/src/app/cart/page.tsx`, `frontend/src/app/checkout/page.tsx` (rewritten presentation), `frontend/src/app/account/page.tsx`
- `frontend/src/components/account/AccountHome.tsx` (new), `frontend/src/components/checkout/st.tsx` (Icon, toman, root class), `stitchDark.module.css` (new)
- `AccountPanel.tsx` unchanged (still serves `/wallet`, `/60coin`, `/60club`).

## Needs from group A (shared)
- `cn()` (`lib/utils`) uses tailwind-merge, which does not know the `st-` font sizes and drops `text-st-label-sm` next to `text-st-secondary`.
  C uses plain `clsx`; a twMerge config extension for st- tokens would fix it site-wide.
- `.material-symbols-outlined { display:inline-block }` (globals) overrides `hidden`/`lg:hidden` on icons — C wraps icons instead.
- Site-wide dark mapping of `st-*` tokens (C and B both use scoped modules).
- Mobile: Stitch 11/17/29 use a compact app bar; the shared header still renders its search row.

## Verification (2026-11-18)
- `npx tsc --noEmit` PASS.
- `NEXT_FONT_GOOGLE_MOCKED_RESPONSES=/tmp/fontmock.js REVIEW_DIST_DIR=/tmp/next-c npx next build` PASS (exit 0); tsconfig/next-env unchanged.
- Checkout journey on the redesigned page (390px, CDP script mirroring `e2e/journey_a.py` selectors: `input.form-input`/`textarea.form-input`
  in the same order, first checkbox = terms, last button matching `ثبت سفارش|پرداخت`): place disabled before terms → enabled → mock-card order
  `ORD-20261118-CDDFA4` created on the TEST DB copy, success view shown. Full `e2e/journey_a.py`: NOT_RUN (Python Playwright not installed here).
- Backend checkout tests: NOT_RUN (pytest not installed in /tmp/venv60); no backend file changed.
