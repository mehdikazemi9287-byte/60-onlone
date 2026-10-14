# Organization Commerce Reality Audit

Observed 2026-09-16 UTC. STATUS: BLOCKED for financial E2E implementation and
acceptance. This is a targeted read-only audit, not release approval. No business
data, application code, roles, flags, services or production deployments changed.
Two audit documents were added in the authoritative checkout. Supervisor and QA
roles were performed locally; no independent-agent review is claimed.

## Proven Blockers

1. Both live catalogs have **zero publicly priced and zero purchasable items**.
   There are also zero fresh eligible offers even ignoring the storefront lock.
   No real safe product exists for the required purchase E2E. No product, price,
   stock or confirmation timestamp was invented to pass a test.
2. Purchase-request approval is not an order/credit/inventory transaction. The
   checkout ledger/reservation infrastructure exists, but the PR bridge does not.
   PR items refer to master products or free text and client estimates; no
   canonical order amount, checkout product/offer binding, request/order unique
   reference or price-increase reconfirmation exists in the inspected PR path.
   Per the task's financial-safety stop rule, no debit or financial mutation ran.
3. Staging container procurement code differs from its worktree. Rebuilding now
   could remove runtime-only visibility/approval changes. The production and
   staging worktrees contain substantial pre-existing work, including protected
   files. A release cannot be assembled by blindly copying this older checkout.
4. No authenticated test session was supplied. Known account memberships were
   read from DB, but login/employee/admin/no-membership authorization was not
   exercised. No organization_finance member exists in either database. No
   account was created, promoted, or assigned new credit for coverage.

## Environment Verified

| Property | Observed evidence |
| --- | --- |
| Host / IP | `ubuntu---2-vcpu---8-gb-ram`, `hostname -I` includes `95.38.183.168` |
| Source checkout | `/home/ubuntu/60online-authoritative`, branch `phase234-20260906T204535Z`, HEAD `9d06e4dbe6cf9a065ad87834e87a761396949a86` |
| Production frontend | `60online-prod-green3.service`, PID observed 3698548, `/home/ubuntu/60online-prod-green3/frontend`, port 3067 |
| Production Git / build | branch `pc-release-20260910T222828Z`, HEAD `30c565ada98704da36e29b8fdee2dea678b8b813`, `.next/BUILD_ID` = `-RN7lI-koT4vWo_VPYY67` |
| Production API | `60online-bluegreen-api`, 8063 -> 8000, image `60online-authoritative-backend:9d06e4d`, image ID `sha256:b0abb006a9d3ac82071436ffd9fde372added04580bbbb99ffcc4ab7c07bb6bd` |
| Production DB | SQLite; container `/blue/70online.db`; host `/home/ubuntu/60online-release-backups/20260906T204535Z/bluegreen/70online.db`; schema/expected 0028 |
| Staging frontend | `60online-staging-fe.service`, PID observed 1323830, `/home/ubuntu/60online-staging-work/frontend`, port 3064 |
| Staging Git / build | branch `staging-impl-20260909`, same HEAD `30c565a...`, `.next/BUILD_ID` = `XSBrHfKy6H0Sm03wwdb4T` |
| Staging API / DB | `60online-stg2-api`, 8064 -> 8000; SQLite `/stage/70online.db`, host `/home/ubuntu/60online-staging-work/stage2/70online.db`; schema/expected 0032 |
| Flags | Both APIs report `APP_ENV=staging`; this does not make the publicly routed API staging. `STOREFRONT_SALES_ENABLED=False` is a code constant, not a verified env override. It was not changed. |
| API origins | Production frontend unit sets `BACKEND_INTERNAL_URL=http://127.0.0.1:8063`; staging sets 8064. 60AI runtime `CORE_API=http://60online-stg2-api:8000`. |
| Ingress | `/etc/nginx/sites-enabled/default`: port 80, domain names 60online.ir/www.60online.ir; `/` and exact `/api/assistant` -> 3067; `/api/` -> 8063 |
| Other running containers | phase234 API 8062; candidate API 8051; legacy backend 8000/frontend 3000; UI test 3001; AI 3070; search 3068; Meili internal 7700. Their names do not prove RC/production roles. |
| Backup evidence | `prod-green3-backup-20260912T191013Z.tar.gz` exists, 229827914 bytes; restore-point directory `20260911140001-pre-commerce-ui` has staging DB/app snapshot. Neither was restored or certified as a complete rollback of today's mixed runtime. |

Source, running container files, frontend build artifacts, staging, RC and
Production remain distinct. No current certified RC or fully tested rollback
point was established. Public DNS/TLS and all alternative processes were not
re-audited; current relevant topology was refreshed from systemd/Docker/Nginx.

## Baseline and Dirty Worktree

The adjacent `2026-09-16-commerce-baseline.json` records branch/HEAD, exact initial
`git status --short` entries and SHA-256 hashes for protected and relevant frontend
files in all three worktrees. Existing authors cannot be inferred from a dirty
diff; ownership is unknown except the prior-turn agent documentation.

- Authoritative checkout initially had only `?? AGENTS.md` and `?? docs/` from
  the preceding bootstrap; those documents were preserved.
- Production has 7 tracked dirty paths: cart page, globals.css, login page,
  homepage, ProductDetail.tsx, PackBuilderInteractive.tsx and Header.tsx.
- Staging has 13 tracked dirty paths plus untracked commerce/AI/media code,
  migrations and stage2 data. Exact Git entries are in the JSON snapshot.
- The reported two-file change is not supported by the current diff:
  `git -C /home/ubuntu/60online-staging-work diff --numstat --
  frontend/src/components/OrganizationPanel.tsx frontend/src/lib/types.ts`
  returns only **98 additions to OrganizationPanel.tsx**. `types.ts` is clean
  relative to staging HEAD. The panel defines a local CreditAllocation type.
  The shared type still requires `amount_minor`, which the real allocation
  serializer does not return; it also omits reserved/consumed fields and uses
  `exhausted` instead of the schema's `revoked`. No type file was rewritten.
- Production/authoritative procurement service hash is
  `c9a2faf93de6b6e5d1eaf31e13b7bb1b2fd940ec24f18eec7484bf8f4a89ce22`.
  Staging worktree has that same hash, but staging runtime has
  `af6799eaf195070b475fd93b165a229a26ce56838c940194b64c908f0cfdc01a`.
  Runtime adds own-request visibility, decision serialization and a budget-only
  credit precheck. This mismatch is a release blocker, not a hidden fallback.

## Compact Contract Map

All paths below start with `/api/v1`. Let P =
`/orgs/{org_id}/procurement`. Facts are source/runtime inspection unless explicitly
listed as live probes. WT means the caller's SQLite `BEGIN IMMEDIATE` write
transaction. It serializes writers but does not create missing financial logic.

| Operation / endpoint | Request and response / states | Authorization | Transaction / retry / UI |
| --- | --- | --- | --- |
| PR create: POST P/requests | title, description, needed_by_date, delivery_province/city/address, optional budget_minor/cost_center/project_code/urgency/notes, items -> `{purchase_request}` in draft, HTTP 201 | Active org member | WT; optional Idempotency-Key with actor/path/body hash, replay 200, different body conflict; OrganizationPanel |
| PR items: nested in create | master_product_id or free_text_description, quantity integer 1..100000, unit, estimated_unit_price_minor, notes | Same as create | Stored in PR WT; estimates are client data, not canonical sale totals; no independent item endpoint inspected |
| PR read: GET P/requests and P/requests/{id} | list `{items,total}`; detail `{purchase_request, ...}` wrapper contains items; filters status/requester_user_id | Active member; production service permits org-wide reads to any member; staging runtime restricts ordinary employees to own requests | Read transaction; runtime adds latest approval action/reason/name/time; OrganizationPanel |
| Submit: POST P/requests/{id}/submit | draft -> submitted; requires at least one item | Requester or org admin | WT; repeated submission conflicts; no order or reservation; OrganizationPanel |
| Decision: POST P/requests/{id}/approve | `{action: approve|reject, reason?}`; submitted/under_review -> approved/rejected; reason persists in procurement_approvals | organization_admin OR procurement_role=approver; organization_finance alone is NOT an approver | WT; repeated terminal decision conflicts; no money/stock/order; OrganizationPanel |
| PR cancel: POST P/requests/{id}/cancel | -> cancelled except awarded/completed/cancelled | Requester or organization_admin | WT; no credit release/refund integration; OrganizationPanel |
| Membership: GET /organizations; GET /organizations/{id}/members | caller's organizations with membership; member details | Authenticated for own org list; membership/role guards for org operations | Read transaction; writes POST/PATCH membership are separate administrative operations, not run |
| Allocation: GET/POST /organizations/{id}/credit-allocations; POST /{allocation_id}/adjust or /revoke | allocation fields include allocated_minor, available_minor, reserved_minor, consumed_minor, validity/limits; states active/revoked/expired | organization_admin/organization_finance via FINANCE gate | WT for mutations, create requires idempotency key; staging panel only fetches as organization_admin |
| Credit view: GET /me/credit, /me/credit/transactions; GET /organizations/{id}/credit-transactions | own allocation wallet totals or ledger entries; allocation/reservation/release/capture/adjustment | Current user for own wallet; FINANCE for org ledger | Read transaction; credit widget/panel; not a cash wallet or 60Coin balance |
| Cart: GET/DELETE /cart, POST /cart/items, PATCH/DELETE /cart/items/{product_id} | product_id/quantity -> cart with server amounts | require_auth(customer), current user scoped | Cart WT; sale eligibility gate; no financial approval; cart UI |
| Quote: GET/POST /checkout/quote | optional redeem_coins -> server cart, tax/shipping, eligibility and funding split | require_auth(customer) | Read/server calculation; distinct from supplier quote or official invoice; checkout UI |
| Checkout: POST /checkout | shipping_address, payment_method, redeem_coins; required Idempotency-Key -> `{order}` | require_auth(customer), current user | Begin WT reserves stock/credit using persisted intent; provider call outside WT; completion WT creates order, captures credit and ledger; fail/reclaim releases holds; no PR identifier; checkout UI |
| Order history: GET /orders and /orders/{order_number}; GET /organizations/{id}/orders | server amount/address snapshots; detail includes fulfillment_orders; order created as pending | Owner/current user or org FINANCE gate | Read transaction; orders UI. No PR/order unique cross-reference in inspected schema |
| Inventory / credit hold | No independent PR reservation endpoint; checkout service calls reserve/capture/release | Checkout service controls caller/transaction | Credit reservation keyed by payment_intent_id; held/captured/released; stock reservation is checkout intent scoped |
| Cancellation/refund/reversal | PR cancel and procurement PO cancel exist; no customer-order cancel/refund endpoint in orders blueprint | PR/PO role checks, not a customer refund authority | Payment failure/abandon compensation exists; captured-credit release explicitly conflicts; no end-to-end PR refund infrastructure |
| RFQ / supplier quote / PO | POST/GET P/rfqs; POST P/rfqs/{id}/award; POST/GET P/purchase-orders; supplier RFQ quote submission | Org procurement/admin and supplier scoping | Procurement WT; RFQ draft/open/closed/awarded/cancelled; separate sourcing chain, not customer checkout; OrganizationPanel reads documents |
| Audit | procurement_audit_log records actor/org/event/entity/details; audit_logs used by credit/admin operations | Written server-side; staging admin audit read endpoint | Same mutation WT; no employee audit-log write endpoint |

PR schema also allows sourcing, quoted, awarded, completed; these are procurement
states, not proof of checkout/payment completion. `request_changes` exists in the
approval table constraint but the decision endpoint accepts only approve/reject.
No UI-only rejection field or fictional pending state was introduced.

## Catalog Readiness

Live SQL used SQLite URI `mode=ro` and `PRAGMA query_only=ON`; public counts used
all pages of GET `/products?page_size=48&page=N`. Counts have different domains:

| Count | Production | Staging |
| --- | ---: | ---: |
| products table total / active | 42 / 42 | 49 / 42 |
| visible catalog publications | 49 | 49 |
| Public API catalog total | 91 | 91 |
| Public positive prices / purchasable | 0 / 0 | 0 / 0 |
| Stored product positive base price (not public price) | 42 | 48 |
| Products with positive inventory row | 14 | 15 |
| Active seller offers / positive offer stock | 34 / 32 | 34 / 32 |
| Fresh eligible offers ignoring storefront flag | 0 | 0 |
| Products blocked only by storefront flag | 0 | 0 |
| Public entries with image_url / missing image_url | 78 / 13 | 78 / 13 |

Stored prices are internal/unpublished candidates, not verified contractual sale
prices. Staging contains 6 pre-existing archived test-marked products and one
non-test draft; these were not created or used here. Of its 48 positive base
prices, 42 belong to the existing active group and 6 to test-marked archived rows.
Images come from linked master_products.image_urls_json, not image_emoji.
Image URL presence is verified; remote availability/authenticity and placeholder
content are NOT VERIFIED. Do not label all 78 images verified real photographs.

Staging already contains admin-only manual price/inventory and CSV/XLSX
preview/confirm workflows, with actor/audit/provenance and explicit authorization
separation. Imports identify existing SKU matches and report applied/failed rows.
Their financial safety, duplicate-within-file behavior, preview freshness and
per-row rollback were not acceptance-tested. They update base price/inventory;
they do not automatically create a fresh eligible seller offer. Therefore the
owner's decision to allow manual data does not yet yield a purchasable product.
No import, publication, confirmation or sales-flag change was executed.

## Financial Lifecycle and Proven Gaps

- Allocation state derives from append-only credit_ledger_entries: allocated,
  reserved and consumed are distinct; available subtracts the latter two.
  Both observed DBs contain only 2 allocation ledger rows totaling 260000000
  minor units, zero reservation rows and no capture rows. This is a ledger
  aggregate, not evidence that all allocations are currently eligible to spend.
- Production has 0 PRs and 10 orders; staging has 5 PRs (2 approved, 1 rejected,
  1 submitted, 1 draft) and 10 orders. These are pre-existing records, not test
  successes. No new request ID, order ID or ledger entry was created.
- Production inventory totals: available 368, reserved 0; staging: available 378,
  reserved 0. Inventory includes legacy/test data and is not public sale stock.
- Staging approval sums active allocations only when budget_minor was supplied.
  It does not derive a canonical price from items, revalidate requester membership,
  price/stock, expiry, blocked status, category/employee/organization limits, or
  reserve anything. Omitting budget bypasses even that optional precheck.
- Checkout already provides persisted intent/item/address/shipping/tax snapshots,
  credit/stock reserve, final capture, double-entry posting and failure cleanup.
  Reuse it; do not implement a separate mutable debit balance in PR status logic.
- Missing financial bridge includes reconfirmation on price increase, unique
  request-to-intent/order ownership, approval retry/race rules, timeout/cancel
  compensation and captured-credit refund/reversal. Partial fulfillment belongs
  to existing fulfillment contracts; its integration here is NOT VERIFIED.
- Wallet cash, allocated organization credit and loyalty/60Coin are separate
  concepts; `/me/credit` is an allocation view, not evidence of a cash wallet.

## Authorization and Regression Evidence

Known identities were read without passwords/hashes/tokens: alice@parsco.ir is an
active employee in org 1; hr@parsco.ir is its active organization_admin;
admin@70online.ir has no membership. Both DBs have 2 active employees, 1 active
org admin, no finance member and no procurement approver role. Organization
switching for authenticated users and cross-org identities remain NOT VERIFIED.

Actual anonymous probes, on both 8063 and 8064:

- GET `/organizations`, `/organizations/1/credit-allocations`, `/me/credit`,
  `/orgs/1/procurement/requests` -> 401 `authentication_required`.
- POST PR create `{}` -> 401; POST PR 1 approve/reject with the actual action
  field -> 401; GET `/orgs/2/procurement/requests/1` -> 401. No identity was forged.
- Staging GET `/internal/products/unknown/pricing` -> 401; production -> 404
  (route absent), which is not proof of equivalent pricing authorization.
- Public catalog scan saw no supplier/internal-price keys in 91 responses per
  environment. This is limited field inspection, not all-role security acceptance.
- The first catalog probe used page_size=100 and correctly received 422; it was
  rerun with supported page_size=48. No successful result is claimed for the
  failed probe.

Employee creation, finance decisions, IDOR as logged-in actors, session/logout,
no protected-content flash, doubles, races, timeout retries, credit/stock changes
and refund scenarios: NOT VERIFIED. No credentials were guessed or sessions
minted from signing secrets. No production balances were modified for a test.

Playwright at `/tmp/pw/node_modules/playwright` was invoked for staging /org,
/account and /login at 390x844 and 1440x1000, but launch failed before any page
loaded: missing chromium_headless_shell-1187 executable. No screenshots or layout
measurements were produced; mobile/desktop/RTL, console and browser network
regressions are NOT VERIFIED. No application build was run because no code was
changed and source/runtime parity is unresolved.

## 60AI Safety Regression

The independent 3070 service and deterministic architecture were left untouched.
Runtime hashes match the inspected registry/context/memory/telemetry source files.
Seven assertions ran in a separate `docker exec ... python -B` process, without
starting an app, using a DB or issuing a chat request:

1. resolve(None) yields anonymous identity.
2. Registry denies guest organization-credit tool.
3. Registry denies guest internal-price tool.
4. create_order policy requires confirmation.
5. Registry denies guest create_order.
6. Direct organization-credit Python call without token raises auth_required.
7. Direct internal-price Python call without token raises auth_required.

All seven passed; they do NOT prove authenticated direct-call non-bypass or
financial execution idempotency. Current create_order/create_promotion tools are
not-implemented stubs. Registry checks capabilities but does not itself enforce
confirmation receipts or an execution idempotency key. No financial AI write was
executed, and no LLM calls were introduced.

Source review confirms server-side identity lookup, but orchestrator retains
client organization context as fallback when resolved organization is absent;
full organization binding is NOT VERIFIED. Telemetry schema excludes transcript
fields, while memory.save persists raw user messages in turns_json (bounded by
turn count). Thus a blanket no-transcript-storage claim would be false. Rate/cost
control enforcement, sensitive-text redaction, authenticated pricing policy and
retry behavior need focused follow-up; they are not marked PASS.

## Existing Promises and Next Backlog

Organizational RFQs, supplier quotes, procurement POs, invoice matching, supplier
settlement/reconciliation and organization summary/credit transactions have code
and endpoints. That is not evidence of a compliant official tax invoice, a real
installment provider or an E2E contractual purchase. Legal/tax behavior was not
changed, and no current legal compliance claim is made.

Next sequence after resolving the blockers:

1. Reconcile runtime-only staging changes into a reviewable source baseline while
   preserving all existing work; establish a rollback that covers that baseline.
2. Use an authorized operator's actual manual price/stock data through the
   existing preview/confirm workflow; verify provenance, duplicate handling,
   rollback and explicit publication without silently enabling sales.
3. Define the smallest PR-to-existing-checkout contract and exactly-once order
   reference, server quote/reconfirmation, finance authority and compensation
   events; add isolated Backend tests before any financial execution.
4. Align shared TypeScript allocation types and panel role/decision consumers to
   verified responses, without rewriting completed auth/profile/org UI.
5. Supply existing safe authenticated sessions and a browser runtime; test real
   roles, approved product, concurrency and after-sales in the identified safe
   environment. Finance coverage remains NOT VERIFIED without a real member.
6. Review AI direct-call confirmation/idempotency and transcript handling without
   coupling it to Pack Builder or adding nondeterministic calls.

## Verification Scope

Evidence commands included git status/diff/worktree/log, systemctl show/cat,
Docker ps/inspect/exec, sha256sum, read-only SQLite aggregate SELECTs, public HTTP
GETs and unauthenticated denial POSTs. No full audit/test suite was repeated.
Final QA checks the two added documents, Git diff/whitespace, protected hashes,
unchanged external worktree statuses and before/after financial aggregates.
PASS applies only to those performed checks, not the requested financial E2E.
