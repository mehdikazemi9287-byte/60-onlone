# LEGACY PACK BUILDER — BEHAVIOR SPEC + PARITY (forensic 2026-09-10)
Legacy source (READ-ONLY): /home/ubuntu/70online/repo/frontend/
- src/pack-builder.js  (5704 B, pure logic, ZERO imports — fully self-contained)
- src/pages/home.js    (UI: mountPackBuilder/renderPackBuilder/tierCard/editablePackPanel, lines ~116-420)
- helpers used: api,session (api.js) · formatAmount,toPersianDigits (format.js) · el,qs,toast,skeletonGrid,showError (ui.js) — generic, not pack-specific
- CSS: public/styles.css  .chips/.chip/.chip.is-active/.pill  (horizontal-scroll chip row)
Legacy API contract:
- api.products({category,q,page_size}) -> GET /api/v1/products?<params>
- api.addToCart(productId, quantity)   -> POST /api/v1/cart/items {product_id,quantity} (auth)
Not referenced anywhere else (loyalty.js match was false positive). No standalone route — mounted at #pack-builder on home.

## LEGACY BEHAVIOR
Entry point: section #pack-builder on homepage; mountPackBuilder() -> renderPackBuilder(slot, state)
Initial state: { budget:null, occasion:null, products:[], loading:false, editing:null, search:'' } ; nothing fetched until both budget+occasion chosen
Product loading: on budget OR occasion pick -> runBuild(): Promise.all(occasion.category_slugs.map(slug => api.products({category:slug, page_size:24}))) ; results flattened; filterPriced()
Category filtering: 6 OCCASIONS each -> fixed category_slugs list (household->appliances,appliance,home-kitchen | supermarket->supermarket,nuts-local,fresh-dairy-frozen | office->office,office-org | digital->digital,laptop,mobile | school->books-stationery | gift->gift-seasonal)
Budget presets: 3 — starter 50,000,000 IRR minor ("۵ میلیون تومان") · standard 150,000,000 ("۱۵ میلیون تومان") · premium 300,000,000 ("۳۰ میلیون تومان")
Recommendations: buildRecommendations(products, budgetMinor) ->
  economy  = fillToTarget(cheapestFirst, floor(budget*0.6)), label "اقتصادی"
  balanced = fillToTarget(cheapestFirst, floor(budget*0.9)), label "متعادل"
  premium  = fillToTarget(priciestFirst, budget),            label "ویژه"
  each tier: {items, total_minor, remaining_minor=target-total, over_budget=total>budget}
  fillToTarget: greedy, qty 1 each, never exceeds target
Tier card: shows up to 4 item lines (name + price) · total · remaining/over · pill "در محدوده بودجه"/"خارج از بودجه" · buttons "افزودن این پک به سبد" + "ویرایش (حذف/جایگزینی/تعداد)"
Empty tier: shows "کالای واجد شرایط با قیمت رسمی برای این بودجه یافت نشد." — NEVER fabricated/filled
Custom flow: "+ پک سفارشی از صفر (جست‌وجوی آزاد)" -> editing = {label:'پک سفارشی', items:[]}
Editable panel (editablePackPanel):
  - item rows: name · qty − / n / + (setQuantity) · line price (price_minor*qty) · remove ✕ (removeItem)
  - budget line (if budget set): "جمع: X" + "Y باقی‌مانده" or "Y بیش از بودجه"
  - search input (min 2 chars) -> api.products({q, page_size:6}) -> filterPriced -> rows with "افزودن" OR "جایگزینی" (if #pb-replace-target select set) ; replaceItem vs addItem
  - "افزودن این پک ویرایش‌شده به سبد"
Price safety: filterPriced keeps only Number.isInteger(price_minor) && >0 — a product without a real price is NEVER shown in recs, tiers, search results, or totals. No invented price anywhere.
Add to cart: requires session.isAuthenticated (else toast "برای افزودن پک ابتدا وارد شوید") ; loops items -> api.addToCart(id, qty) one call each ; toast success/fail per pack
Loading state: skeletonGrid(3) while runBuild in flight
Error state: showError(slot, error) on fetch failure
Reset/remove: setQuantity(id,0) -> removeItem ; removeItem drops matching line only
Desktop UI: chips row + grid of 3 tier cards (.grid)
Mobile UI: .chips horizontally scrollable, cards stack
Persistence: NONE (pure client state; server cart/checkout authoritative)

## PARITY — LEGACY vs NEXT.JS RESTORED (staging b51efef)
| FEATURE | LEGACY | RESTORED | STATUS | NOTE |
|---|---|---|---|---|
| Mounted at #pack-builder on homepage | YES | YES | PASS | section id + section-shell + scroll-mt-28 |
| No standalone route | YES | YES | PASS | /pack-builder -> 307 redirect to /#pack-builder |
| 3 budget presets (5/15/30m, exact minor values) | YES | YES | PASS | BUDGET_PRESETS_MINOR ported verbatim |
| 6 occasions -> category_slugs | YES | YES | PASS | OCCASIONS ported verbatim; all 13 slugs valid in current 20-cat taxonomy |
| Fetch on budget/occasion pick (page_size 24, per slug) | YES | YES | PASS | catalog.list({category,page_size:24}) == api.products |
| filterPriced (never invent price) | YES | YES | PASS | ported verbatim; unit test 1 |
| buildRecommendations economy/balanced/premium (0.6/0.9/1.0, cheap/cheap/pricey-first) | YES | YES | PASS | ported verbatim; unit tests 8,9 |
| Tier card: 4 lines + total + remaining/over + pill | YES | YES | PASS | |
| Empty tier NOT fabricated | YES | YES | PASS | honest message; unit test 9; live: all tiers empty (catalog price_minor all null) |
| Custom pack from zero | YES | YES | PASS | "+ پک سفارشی از صفر" |
| Editable panel: qty +/- | YES | YES | PASS | setQuantity; unit test 5 |
| Editable panel: remove | YES | YES | PASS | removeItem; unit test 4 |
| Editable panel: replace (search-and-swap + target select) | YES | YES | PASS | replaceItem; unit test 6 |
| Editable panel: search-add (min 2 chars, page_size 6, filterPriced) | YES | YES | PASS | catalog.list({q,page_size:6}) |
| Budget tracking (total/remaining/over) | YES | YES | PASS | budgetState; unit test 7 |
| Add pack to cart (auth required, 1 call/item) | YES | YES | PASS | cart.add(token,id,qty) -> POST /api/v1/cart/items ; token gate |
| Loading skeleton | YES | YES | PASS | 3 skeleton cards |
| Error state | YES | YES | PASS | red alert card |
| RTL / Persian digits / currency | YES | YES | PASS | html dir=rtl; toLocaleString("fa-IR"); no forced LTR |
| Desktop (grid of 3) / Mobile (stack) | YES | YES | PASS | md:grid-cols-3; flex-wrap chips; 0 fixed-px widths |
| Persistence | NONE | + optional server "ذخیره پک" / "پیش‌فاکتور" | ADDITIVE | compat addition, does not replace/simplify; original had none |
| Styling | legacy CSS (.chip/.chips) | Tailwind equivalents | ADAPTED | legacy CSS not present in Next.js app — visual concept preserved (chip rows, tier cards, editable list) |

NOT RESTORED: none. (1 ADDITIVE item = server-side save/proforma, kept from Phase 4; can be removed on request.)
DATA DIVERGENCE (documented): current catalog has price_minor=null for all 91 products (storefront sale-lock + no verified offers). Legacy assumed priced products exist. filterPriced correctly yields 0 -> all recommendation tiers render the honest empty state. This is identical to how the legacy engine behaves given today's data — no adaptation was needed beyond what filterPriced already guarantees.
