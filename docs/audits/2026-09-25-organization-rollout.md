# Organization rollout — 2026-09-25 UTC

Status: PARTIAL implementation; ENVIRONMENT PRESERVATION FAIL. This is not a Production acceptance report.

**Incident:** cleanup stopped two pre-existing alternative Next listeners3062/3063 in addition to the owned preview. They remain stopped pending verified recovery configuration/artifact. The active domain ingress3067/8063 and public3051 were rechecked and remain available. Do not read successful source tests as an overall release PASS. Full details below.

## Baseline and independent gates

Project root `/home/ubuntu/60online-authoritative`; branch `phase234-20260906T204535Z`; HEAD `9d06e4dbe6cf9a065ad87834e87a761396949a86`. Initial status: untracked `AGENTS.md`, `docs/`; preserve these existing files. No application dirty paths initially. Independent Supervisor agent `/root/independent_supervisor` reviewed policy, source/schema evidence and scope before edits.

S1 ALLOW: source procurement service/API, additive SQLite migration0034, isolated tests and this new report. Intake must not post money, reserve credit/stock or create an order. Ordinary employee reads own requests; elevated organization procurement roles remain organization-scoped. Unsupported attachments must be rejected. Existing Staging work is excluded.
S2 ALLOW: additive organization page in existing Figma file, existing masters/pages preserved. Future workflows explicitly DESIGN ONLY / NOT_IMPLEMENTED. No real business or financial rows invented.

## Current observed environment

- Host `ubuntu---2-vcpu---8-gb-ram`, inspected 2026-09-25.
- Public GET `http://95.38.183.168:3051/`: HTTP200. PID1062932 working directory `/home/ubuntu/60online-image-backups/20260822T193000Z-3050-frontend/candidate-source`; API readiness through3051 returns schema/expected0027. Its process BACKEND_INTERNAL_URL is http://127.0.0.1:8051. This is a distinct runtime, not proof of domain Production equivalence.
- Nginx actual `/etc/nginx/sites-enabled/default` names `60online.ir`, `www.60online.ir`, `95.38.183.168`, listens80, routes `/` and `/api/assistant` to3067, `/api/` to8063. DNS A answers observed185.143.234.130 and185.143.233.130; public HTTPS returned200. These CDN-facing observations do not independently prove CDN origin configuration or full TLS posture.
- Docker `60online-bluegreen-api`, image `60online-authoritative-backend:9d06e4d`, host8063; bind `/home/ubuntu/60online-release-backups/20260906T204535Z/bluegreen` to `/blue`, writable. GET readiness200 with schema/expected0028.
- Actual SQLite `70online.db` under that bind inspected with URI mode=ro and query_only. `purchase_requests` has one delivery address; no multidestination intake structure observed. Schema and endpoint health are not business acceptance tests.
- Git origin matches `git@github.com:mehdikazemi9287-byte/60-onlone.git`. SSH `git ls-remote` succeeds: remote HEAD/main `96c03d02aa8a2a1134043c66425988c1c32c4aea`; local task branch was not returned by the exact remote-ref query. GitHub connector itself is unauthenticated. No push/fetch/checkout performed.
- Staging source has substantial pre-existing tracked/untracked work, including protected UI and financial bridge; max migration0033. September16 release report is historical credit-only test evidence; synthetic offers must never become Production data.
- Figma read succeeds; original pages `0:1` Homepage/Desktop and `2:2` Components. Production CSS/layout specify Vazirmatn. Figma and deployed layout parity not yet certified.
- September25 research document was not found in bounded local documentation searches; original source requested from user. No comparison with unavailable research claimed.

## Proposed operational responsibility matrix

This is the implementation contract proposed from the requested process, not a claim that the company has appointed these officers. Real assignments and finance mandates must be supplied/approved by the company.

| Action | Authorized role/scope | Responsible party | Required audit and control |
|---|---|---|---|
| Create/submit request | active organization requester | requester | actor/org/request/version/time; submission is not an order |
| Triage and assign case | internal operations with explicit scope | assigned case owner | assignment history; no implicit financial authority |
| Review organizational need | organization approver/admin | designated approver | decision/reason/version; only own organization |
| Source and invite suppliers | assigned internal procurement | case owner | supplier invitation and response, failure reason, line allocation |
| Set offered price | authorized pricing operator | pricing owner | immutable quote version, real source costs, currency and expiry |
| Approve customer offer | authorized organization approver | customer approver | exact accepted version, totals, payment terms, destinations; material change requires new approval |
| Buy from supplier | authorized internal purchasing | procurement owner | supplier PO snapshot, authorization and delivery commitment |
| Dispatch/accept delivery | fulfillment operator / destination recipient | fulfillment owner | item/destination quantity events; partial/short/returned quantities reconciled |
| Resolve discrepancy | internal case owner with customer participation | discrepancy owner | evidence, decision, credit note/refund proposal; no silent balance rewrite |
| Reconcile bank deposit | independent internal finance verifier | finance reviewer | bank evidence and matched transaction; uploader cannot approve own payment |
| Receive cheque | internal finance custodian | cheque custodian | cheque identity, amount, due date, receipt and custody; receipt is not cash collection |
| Clear/return cheque | independent internal finance verifier | finance reviewer | actual clearance/bounce evidence; append-only reversal |
| Change credit limit/refund | authorized proposer + distinct approver | finance reviewer | approved policy version, reason and compensating ledger entries |

## Payment activation prerequisites (not implemented by this tranche)

Default unavailable unless the actual organization/contract has an approved policy. Do not infer cash, cheque, credit, installment, deposit or mixed-method entitlement from a generic role or a Staging flag.

Cash online requires a real configured provider and authenticated/reconciled callback; bank transfer remains pending until verified. Cheque states must distinguish expected, received, transferred, collected, bounced and returned. Credit available/reserved/debt/overdue must reconcile to an append-only ledger, with atomic reservations and compensating releases/refunds. Approved limits are not cash balances. Quote acceptance snapshots currency, amount, expiry, installments and policy version. Taxpayer-system integration and official-invoice designation remain disabled without actual legal/finance decisions and valid connection.

## Contract discrepancies and release blockers

Source/3051/domain API schemas differ. Frontend browser client uses configured NEXT_PUBLIC_API_URL or same-origin `/api/v1`; dedicated intake must consume the verified `{items}` organization list and `{purchase_request}` request wrapper, bearer authentication and backend error envelope. Quantity currently integer; currency configuration in tests IRR exponent0 is test evidence only, not confirmation of every runtime currency. Request list currently unpaginated `{items,total}`; do not advertise pagination. New multidestination fields require migration0034 and matching backend before frontend release.

Source frontend differs from deployed protected Homepage/PackBuilder. No whole-checkout release is safe without reconciliation. No current RC, backup/rollback certification or concrete Production deployment approval exists. No live migration, service restart, routing switch, payment or financial test is authorized by these source gates.

## Verification and remaining work

Source changes, isolated API/browser tests, Figma frames and independent code review are complete for S1-S4 only. Overall operational QA is FAIL because of the cleanup incident below. Historical Staging test counts are not current results. Required full cash/cheque/credit workflows, secure uploads, internal case management, supplier failure, two-destination shortage, quote expiry, partial return and delivery/finance panels remain unverified until implemented and tested.

S3 ALLOW: dedicated source route `/organization/requests` and route-local files only, consume current memberships/auth/API, retain idempotency on identical retries and discard stale cross-organization responses. No shared/protected edits. S3-QA ALLOW: temporary loopback-only API/Next, fresh test DB, synthetic test identities and browser container, explicit isolated origin; stop owned processes afterward.

Current TypeScript baseline: `frontend/node_modules/.bin/tsc --noEmit --incremental false` exited0 before frontend edits. This is static baseline only.

Upload implementation acceptance will use authorized ownership checks, extension/content/signature validation, quotas, quarantined private storage and controlled downloads. No unscanned arbitrary URL acceptance is substituted for uploads. Research source: [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html), consulted2026-09-25; this is security research, not the missing business-readiness research.

## Implemented tranches and current evidence

- S1 source: migration0034 persists validated destinations and substitution policy. Allocation item indexes are zero-based and quantities must sum exactly per requested line. Requester/admin/approver/procurement/finance reads are scoped; ordinary employee sees own requests. Creation/replay/submission require active organization; tracking stays available to authorized existing members. Unpriced free-text and catalog identities with optional estimates supported; this is not published-price verification. Files: procurement service/API, migration0034, test_organization_intake.py.
- S1 final isolated command: disposable existing backend image, `--network none --read-only --tmpfs /tmp`, source bind read-only, explicit unittest entrypoint; `python -m unittest tests.test_organization_intake tests.test_procurement_replay tests.test_procurement -q`: 42 PASS in60.403s after inactive-org fix. Temporary SQLite tests cover no side effects across existing financial/order/inventory tables. This is source API integration verification, not Production E2E.
- S4 independent ALLOW: operations service/API, migration0035, tests and main.py blueprint wiring only. New staff capability grants start empty; platform admin and customer memberships grant no internal access. Manager assignment, assigned-agent visibility, active-org/grant checks, versioned transitions and mandatory idempotency write append-only audit atomically. No request/order/financial-state mutation. Real staff mandate provisioning is deliberately absent pending company authorization.
- S4 final isolated operations suite: 7 PASS in11.527s, including zero-ID404, authorization/revocation, stale/conflicting replay, immutable events and forced audit failure rollback. Log `/tmp/60online-operations-test.log`. No live grants or migration applied.
- S3 new route `/organization/requests`: actual auth/membership/list/detail API, dynamic lines/destinations, explicit draft then submit, receipt/cancel, response-loss retry with stable key and synchronous double-click lock. Unit required; money/length limits aligned. Optional budget enabled only when returned organization currency is IRR, labeled ریال. Catalog input currently requires a real master-product ID manually; catalog search/selection UX remains incomplete. Upload unavailable.
- Independent Backend/Security review found and corrected optional unit mismatch, excessive client limits, validation-error form lock, unsafe retry reset, assumed currency, inactive-org mutations, and zero-ID operations500. Browser functional checks passed; final evidence and incident qualification follow below.

## Figma evidence

Additive page [Organization /2026-09-25](https://www.figma.com/design/Q4lD8SJ0MfZzHTAM94NUpQ?node-id=130-218). 20 desktop/mobile frames, all with route/role/backend annotations; read-back408 text nodes all Vazirmatn. Existing pages/masters were not edited. Intake desktop/mobile screenshots, corrected intake mobile, finance mobile and state catalog mobile inspected by design agent. Role panels are PARTIAL design specifications/empty or disabled states, not complete operational interfaces.

| View | Desktop node | Mobile node | Implementation scope |
|---|---|---|---|
| Intake |130:219|130:220|Source route; isolated browser PASS|
| Receipt/tracking |130:221|130:222|Source receipt; full visual parity not certified|
| Requester |130:223|130:224|Dedicated intake/tracking route only|
| Org admin |130:225|130:226|Design only; existing panel not re-certified|
| Approver |130:227|130:228|Design only; existing API not complete commercial approval|
| Org finance |130:229|130:230|Design only / disabled future workflow|
| Internal operations |130:231|130:232|New case API only; no new operations UI|
| Supplier |130:233|130:234|Design only; existing sourcing API not full new flow|
| Internal finance |130:235|130:236|Design only / disabled future workflow|
| State catalog |130:237|130:238|12 state specifications, not individually executable flows|

State specifications cover empty/error/waiting/denied/shortage/supplier failure/expiry/approval/cash/cheque/credit/dispute-cancellation-partial-return. Technical annotations are outside product UI. Intake destination fields corrected to actual contract; unsupported contact fields removed. Dynamic repeated data fields and existing site Header/Footer require separate runtime parity review; protected shared UI is intentionally preserved.

Initial browser run against Next development mode FAIL: existing CSP blocks webpack unsafe-eval, leaving hydration pending. No shared security setting was weakened. Production-mode source build selected for isolated browser verification instead. This is a test-environment finding, not proof of a Production regression.


## Final verification evidence and limits

Independent Supervisor executed assembled backend suites once after final API fixes: 49 tests PASS in68.020s, exit0. Command: disposable `60online-authoritative-backend:9d06e4d`, `--network none --read-only --tmpfs /tmp`, read-only backend source, `python -B -m unittest tests.test_organization_intake tests.test_procurement_replay tests.test_procurement tests.test_organization_operations -q`. Intentional audit insert error is expected rollback coverage.

Final source Next production-mode build PASS (log `/tmp/60online-org-qa-20260925/frontend-build.log`). Temporary browser API used fresh AppTestCase SQLite/test settings, synthetic actors and no production records or secrets. Actual Chromium results:

- `browser-results.json`: anonymous and no-membership mobile; employee390/1440; RTL, Vazirmatn, no horizontal overflow or page errors; two items/two destinations, draft→submit→cancel; synchronous double-click produces exactly one POST; other employee GET404.
- `retry-results.json`: actual API422 leaves correction possible; dropped response after server201 followed by same-key replay leaves exactly one persisted request.
- `visual-results.json`: final CSS-only correction rechecked at390/1440; required marker stays on label line, RTL/font/no-overflow pass. Screenshots `final-390.png`, `final-1440.png`; source CSS fixed only new route. Other source feature assertions remain applicable. Figma/runtime full visual parity is PARTIAL: existing protected Header/Footer, dynamic field count, separate membership selector/list and receipt layout differ from static designs.
- Initial browser failures were distinguished: development-mode CSP hydration failure; then test locator did not account for required marker, expected403 instead of contract404, and matched Next announcer as a second alert. Tests corrected, no business behavior weakened.
- Protected SOURCE file hashes for Homepage, PackBuilder, globals.css, layout.tsx and Header.tsx match intake baseline. This proves unchanged source files only; see artifact/service incident below.

Temporary test API container stopped and its transient DB removed with container tmpfs. Synthetic session fixture deleted; scripts/results/screenshots retained under `/tmp/60online-org-qa-20260925`. They are evidence, not Production data. No commit/push/deployment or live DB migration/business/financial transaction was performed.

## Current financial reality

Read-only actual publicly routed backend configuration inspection: APP_ENV=staging; PAYMENT_PROVIDER and CREDIT_PROVIDER unset in Docker environment, deployed load_settings defaults both to mock. Deployed currency defaultsIRR exponent0. Deployed STOREFRONT_SALES_ENABLED=False; TEST_SALES_OVERRIDE, DEMO_MODE and STAGING_MANUAL_SALES_ENABLED unset. These observations do not establish a valid payment gateway. APP_ENV label does not change this runtime's Production routing.

Actual live schema has no table name matching policy/cheque/contract; one active organization; memberships aggregate2 active employees and1 active organization_admin, no organization_finance member in that table. No real internal mandates or payment policy were fabricated. Company finance/legal policy, actual provider and real staff-authority mapping requested; no reply available at report time.

## Cleanup incident — unresolved

The parent agent incorrectly used source working-directory equality as an ownership test when stopping Next servers. The script issued SIGTERM to PIDs120434,2495690,3680785. Only2495690 was the owned3181 preview. Intake evidence had already shown120434 on3063 and3680785 on3062. They were pre-existing processes, not task-owned.

Independent read-only recovery evidence:

- `/home/ubuntu/60online-release-backups/20260906T204535Z/frontend-bluegreen.pid` is120434; its log identifies127.0.0.1:3063.
- `frontend-staging.pid` is3680785; its log identifies127.0.0.1:3062.
- Both processes also used the authoritative frontend cwd. Earlier isolation inference checked domain/3051/staging3064 and Docker binds but omitted these alternative listeners. Running Next build in that directory overwrote `.next`; prior artifact parity for3062/3063 is therefore not certifiable.
- No matching systemd startup unit or PID journal evidence located; narrow port-specific shell-history search returned zero entries. Exact prior BACKEND_INTERNAL_URL and prior build artifact remain unknown.
- Dated `frontend-active.tar.gz` contains a `.next` but manifest explicitly identifies the3051 candidate-source/96c03d0 baseline. It is not verified recovery for3062/3063 and was NOT restored over newer work.
- After incident, `ss` shows3051 PID1062932 and3067 PID3698548 still listening; publicly routed API8063 container remains healthy/up2weeks. GET3051 and local Nginx Host60online.ir return200; API readiness remains0028. No claim of full public product/regression QA is made.
-3062 and3063 remain down. No blind restart with the new0035-capable frontend against old backend was attempted. Independent Supervisor marks environment preservation FAIL and recovery BLOCKED pending correct startup configuration and artifact. User was informed and asked for the missing launch/build reference.

Correct next operation: establish exact prior launch environment and approved matching artifact for each affected listener; prepare a separate isolated recovery copy and concrete reviewable start/rollback commands; obtain the applicable independent gate and any required concrete operation approval before starting them. Do not restore the3051 archive by assumption or run the new source build as the old runtime.

## Acceptance matrix

| Capability | Status | Executed evidence | Figma | Production / remaining gap |
|---|---|---|---|---|
| Multi-item/multi-destination intake and tracking | PARTIAL | isolated API + Chromium PASS | desktop/mobile created | Not deployed; manual catalog-ID input, integer units only, secure upload absent |
| Intake no-order/no-reservation/no-money invariant | PASS (source scope) | whole-table side-effect snapshots;49 combined suite | receipt warning | Live new behavior NOT_RUN |
| Membership isolation/idempotency | PASS (tested source scope) | API unauthorized/revocation tests; browser404/lost-response replay | denied/pending states | No Production rollout |
| Internal case ownership/audit | PARTIAL |7 operations tests within49 | role view draft | API only; no real mandates or internal UI; no full purchasing/delivery execution |
| Organization/admin/approver/finance/supplier panels | PARTIAL | existing APIs inspected, new intake UI only |20 total frames incl role specs | Full action/data wiring unfinished |
| Cash/cheque/credit contract policy and reconciliation | BLOCKED activation; implementation incomplete | No full new financial E2E executed | disabled design states | Valid policy/provider/legal decisions absent; existing code not complete new contract |
| Versioned customer quotes, multi-supplier purchasing, quantitative delivery, shortages and partial returns | PARTIAL | pre-existing procurement regression coverage only | draft state specs | Requested full workflow not implemented/accepted |
| Safe file attachments / official invoice / taxpayer integration | BLOCKED | Upload explicitly rejects unsupported data; no fake connection | disabled states | Storage/scanner/authority or genuine legal integration evidence missing |
| Source protected UI preservation | PASS (files only) | exact five source hashes | existing masters/pages preserved | Full runtime regression NOT_RUN; alternative artifact incident |
| Operational preservation/release | BLOCKED; incident FAIL |3062/3063 stopped; active ingress availability verified | N/A | Recovery reference required; no RC/verified rollback or deployment approval |

The user's completion criterion has NOT been achieved. No claim of launched organizational ordering or completed remaining phases is made.
