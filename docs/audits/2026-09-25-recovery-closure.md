# Recovery and closure baseline — 2026-09-25

Scope: 60Online only. Source branch `phase234-20260906T204535Z`, HEAD `9d06e4dbe6cf9a065ad87834e87a761396949a86`; all pre-existing S1/S3/S4 dirty work retained. This document supplements, not overwrites, [previous incident/evidence](2026-09-25-organization-rollout.md).

## Recovery chain

| PORT | SERVICE | WORKDIR | START COMMAND | BUILD/COMMIT | ENV SOURCE | EVIDENCE |
|---|---|---|---|---|---|---|
|3062|Historical frontend-staging process PID3680785; no verified service definition|/home/ubuntu/60online-authoritative/frontend|UNKNOWN|Pre-incident immutable artifact/commit UNKNOWN|UNKNOWN|Dated frontend-staging.pid/log; prior process evidence; retained September15/16 session observations|
|3063|Historical frontend-bluegreen process PID120434; no verified service definition|Same authoritative frontend|UNKNOWN|Pre-incident immutable artifact/commit UNKNOWN|UNKNOWN|Dated frontend-bluegreen.pid/log; prior process evidence; retained September15/16 session observations|

RECOVERY_3062: BLOCKED. RECOVERY_3063: BLOCKED. Current affected-port listener check remains empty. No restore plan can identify the previous baseline without guessing. Backup directory is `/home/ubuntu/60online-release-backups/20260906T204535Z`. `frontend-active.tar.gz` belongs to the separate3051 candidate according to its manifest; excluded from recovery. Previous systemd/journal/history/nginx/launch searches reused. Supplemental bounded retained session evidence adds only listener observations, not missing launch/environment/artifact provenance. No build, migration, service launch/restart, artifact restoration or routing change occurred in this stage.

Independent Supervisor `/root/recovery_supervisor`: read-only recovery ALLOW; recovery/Production BLOCKED; S6 source-only ALLOW for operations context, dedicated route, directly-new tests and this report. Prior incident environmental FAIL is not erased by new code tests.

## Frozen evidence

49 Backend tests and browser double-click/two-destination/submit-cancel/authorization/response-loss tests were NOT repeated. They remain historical evidence for the previous exact scope. Existing20 Figma frames preserved. Live metadata check mode=ro/query_only confirms purchase request/membership tables exist, organization_operations tables do not; live deployment is not the new source schema.

## IMPLEMENT

| OWNER | STATUS | BLOCKER | NEXT ACTION | EVIDENCE |
|---|---|---|---|---|
|Backend / request→case context|SOURCE PASS, independent source review PASS|None for code; deployment gate separate|Retain5 new regression results; final QA gate|New operations discovery GET and organization-constrained linked request/items/destinations;5 new tests0.108s|
|Frontend / internal case management|SOURCE PARTIAL|Runtime NOT_RUN; no approved isolated artifact/preview used this stage|Review source then verify only new workflow in approved isolated environment|/operations/requests uses actual grants, cases, ownership/versioned actions and existing audit; TypeScript exit0|
|Backend+Frontend / catalog selection and secure attachments|TODO|No code-policy blocker; attachment storage/scanner activation is ACCESS/INFRA|Real catalog selector; private quarantined upload workflow|Previous intake uses manual master-product ID; attachments explicitly unavailable|
|Backend / versioned customer offer and multisupplier allocation|TODO|Policy approval required only for binding financial terms|Implement immutable version/expiry/customer reapproval and real line allocations|Previous RFQ/PO code exists; no accepted new full workflow evidence|
|Backend / quantitative deliveries and receipts|TODO|Real dispatch integration and actor scope required for activation|Persist per-destination dispatched/accepted/short quantities and audited receipts|Case status alone does not prove physical delivery|
|Backend+Frontend / discrepancy and partial return|TODO|Financial cancellation/refund policy is separate POLICY row|Implement recorded nonfinancial claim/evidence/authorization before settlement|Prior state catalog is specification, not working return flow|
|QA / new operations E2E|PARTIAL|No approved isolated artifact/preview used this stage|Review and later run only changed UI→API→persistence→authorization→audit flow|5 new real-JWT Flask test-client read-context tests; existing mutation audit tests reused, not re-run|

## POLICY

| OWNER | STATUS | BLOCKER | NEXT ACTION | EVIDENCE |
|Company finance / cash|NEEDS DECISION|Approved organization-specific prepayment/deposit and matching authority absent|Supply approved policy and authorized independent reconciler|Prior live provider selectors unset, deployed defaults mock; no genuine provider certified|
|Company finance / cheque|NEEDS DECISION|Acceptance, due date, custody, transfer, clearance/bounce rules absent|Approve cheque lifecycle and authority separation|No live contract/cheque policy tables observed previously|
|Company finance / credit|NEEDS DECISION|Approved limit, eligibility, reconciliation and independent approval authority absent|Provide per-contract limit/terms plus reconciled opening balance|Existing credit ledger is not proof of a new approved policy|
|Company finance/legal / bill or undertaking|NEEDS DECISION|Instrument meaning, enforceability, acceptance and discharge not specified|Define instrument and approved obligations; no cash equivalence by assumption|User explicitly requests برات/تعهد; no verified company decision supplied|
|Company finance / allocation|NEEDS DECISION|Delegation scope and organization/employee allocation rules not approved|Specify allocation/reservation/release authority and hierarchy|No real new grants/limits assigned|
|Company finance / maturity and collection|NEEDS DECISION|Due-date, installment, overdue and actual collection recognition rules absent|Approve schedule/calendar and evidence for recognizing collection|Receiving an instrument must not imply collection|
|Company finance/legal / cancellation and returns|NEEDS DECISION|Refund entitlement, offsets, partial returns and independent approval rules absent|Approve compensating-event and credit-note/refund policy|No new complete financial return E2E|
|Company finance / settlement and invoices|NEEDS DECISION|Accepted reconciliation, mixed payment, settlement and official invoice authority absent|Define reconciliation ownership, official invoice/taxpayer obligations|No official invoice or taxpayer connection fabricated|

## DESIGN

| OWNER | STATUS | BLOCKER | NEXT ACTION | EVIDENCE |
|Design / internal operations detail and actions|PARTIAL|Baseline is draft, not an authority blocker for Backend|Verify runtime parity when permitted|Existing130:231/232 retained; additive Source S6 frames136:306/136:330; no runtime parity claim|
|Design / requester-admin-approver-supplier panels|PARTIAL|Action/data states still incomplete|Complete states against verified workflow, preserve existing frames|20 baseline frames on page130:218; prior report maps roles and routes|
|Design / finance-delivery-return panels|DRAFT|Financial wording needs POLICY decisions|Design nonfinancial states now; mark unsupported financial actions unavailable|Existing state catalog130:237/238 is not runtime verification|

## ACCESS/INFRA

| OWNER | STATUS | BLOCKER | NEXT ACTION | EVIDENCE |
|DevOps /3062 recovery|BLOCKED|Exact start/env and immutable previous artifact missing|Locate authoritative launch record and matching retained build; independent Recovery Plan gate before restore|Recovery chain above|
|DevOps /3063 recovery|BLOCKED|Same missing provenance|Same evidence-driven plan; never substitute current build|Recovery chain above|
|Company owner / internal mandates|BLOCKED activation|Actual staff accounts, organization scopes and mandate references absent|Supply genuine assignment authorization; do not infer customer membership as staff|Source grants default empty; new discovery lists only actual active grants|
|DevOps / upload storage and scanner|BLOCKED activation|Private storage/scanner configuration and access not verified|Verify existing authorized services or prepare concrete infrastructure proposal|Current intake rejects unsupported attachments|
|Integration / payment and official invoicing|BLOCKED activation|Valid provider/credentials/company legal configuration absent|Receive approved integration access and policies|Previous deployed configuration evidence; no fake connection|
|DevOps+Supervisor / production release|BLOCKED|Recovery unresolved, financial/delivery/return closure incomplete, final release PASS absent|Close dependencies, prepare immutable candidate/backup/rollback and gate|User explicit release prohibition|
|Research owner / September25 readiness study|BLOCKED comparison|Referenced original study not located/provided|Supply exact source/path, then compare only relevant conclusions|Prior bounded research search and user request pending|

## Stage verification

Only `tests.test_organization_operations_context` ran:5 PASS; synthetic in-memory schema, real JWT and Flask test client, no migrations/listening service/network, disposable existing-image test process. Tests cover mandate discovery, admin/token non-bypass, assigned request/destination context, no read side effects, cross-organization corrupt link rejection, revoked grant/inactive organization/user. New route TypeScript check passed; no runtime UI/Figma-parity claim. Independent source review PASS; final narrow source/report stage review PASS; overall baseline/release BLOCKED. Figma additive desktop/mobile frames136:306/136:330 preserve the original20; mobile screenshot exposed button wrapping, corrected only in the two new frames; postfix mobile screenshot inspected and wrapping resolved. Desktop screenshot and runtime parity remain NOT_RUN. These are source workflow specifications, not proof of runtime UI parity. Exact token consumption unavailable; no estimate.

## S7/S8 operational continuation — current evidence supersedes S6 runtime NOT_RUN

Independent prechange ALLOW: `/root/recovery_supervisor` S7 (isolated build/migration/browser and operations fixes), S8 (read-only finance readiness), additive four Figma frames. No Production action authorized or performed. Source HEAD remains9d06e4d; previous dirty work preserved.

Recovery supplement: standard PM2, Supervisor and user-systemd definitions absent at inspected paths. Branch reflog dates96c03d0→c8c46d4→9d06e4d, but does not bind either affected port to a launch/env/artifact. Both recovery chains remain BLOCKED; neither port started.

### Delivered source

- Operations route now restores authorized organization/case selection through URL and refresh; scoped detail loading, actionable read-error retry and invalid-organization escape; form reason clears when case changes. Existing real grant authorization, version checks, idempotency and append-only audit remain authoritative. Customer organization roles never imply internal staff mandates.
- New `organization_finance_policy` service/GET API and `/organization/finance`: active organization plus active organization_admin/organization_finance membership required; employee, other tenant, revoked membership and platform-role bypass denied. Nine readiness categories and five method identifiers, all disabled, no invented financial terms/limits/balances. Readiness describes this panel only: legacy payment/credit APIs were not disabled. No approved-policy persistence/approval/financial execution engine is claimed.
- Homepage/PackBuilder/shared CSS/auth/API client untouched. Source deployment still differs from historical live protected UI; full source build is NOT a deployable production revision by implication.

### Verification

Evidence directory: `/tmp/60online-s7/evidence`; harness scripts in `/tmp/60online-s7`.

| Check | Actual result and scope |
|---|---|
| Build | PASS: isolated copied frontend `NEXT_PUBLIC_API_URL= npm run build`; final `build-final.log`, exit0. No source .next rebuild. |
| New backend tests | PASS: `tests.test_organization_finance_policy`,3 tests0.103s, real JWT/Flask with synthetic in-memory schema. Prior49 and5 frozen, not repeated. |
| Migration dry run | PASS: synthetic SQLite0028→0035, applies0034/0035; integrity/FK checks OK, initial staff grants0, repeat upgrade no-op; `migration.json`. Not a rehearsal on a copy of production records. |
| Browser operations | Scoped PASS across recorded runs: actual password login, empty list, create, double-click exactly1 POST, assign/reassign, audit3 events, replay same key without extra event, prior assignee403; direct case URL/refresh, desktop1440/mobile390 RTL/no overflow. `browser.cjs`, `remaining.cjs`, manager/final-operations screenshots. |
| Browser permissions | PASS: organization_admin/organization_finance/employee at both widths; explicit forbidden org/case URL and API403; cleared URL returns no-grant state. `operations-final.cjs`, six denied screenshots. These roles correctly cannot perform internal assignments. |
| Browser retry | PASS: assigned case_agent transition loses response after server commit, retries same action, event count4 (only one new event); API503 shown and retried successfully. `retry-transition.cjs`, `final-browser-results.json`, `transition.log`. |
| Browser finance | PASS: six role/viewport cases, all9 actions disabled for allowed roles, employee UI/API denied, refresh; `finance-browser-results.json`. Loading/API503/retry PASS separately, `finance-error-results.json`. |
| Secrets | PASS limited targeted credential-pattern scan of7 changed production-source files, no findings; `source-scan.json`. Not whole-repository or historical certification. |
| Isolated health | API readiness200 and both new routes200; `health-api.json`. Health is supplementary, not product QA. |

Failures corrected without repeating unrelated passes: test login selector ambiguity; harness doubled API prefix; actual invalid-org recovery link needed full route reload (fixed); Playwright smooth scrolling conflicted with sticky navigation during mobile click (centered the control with instant test scrolling before a real click; no shared CSS/force-click bypass). Tests were continued from already-persisted successful case state rather than resetting/replaying successful creation. No single clean all-scenarios suite-run is claimed.

### Design mapping

22 baseline frames preserved. Added same-file editable runtime-reference frames: operations desktop138:310/mobile138:537; finance desktop138:764/mobile138:905. Derived from isolated route DOM measurements and existing component instances; test records explicitly marked synthetic. Corrected observed instance-label wrapping. Screenshots reviewed for desktop/mobile layouts and Persian RTL; minor spacing/native-select/shared-shell differences mean pixel-perfect parity remains PARTIAL. Other original draft panels (supplier, approval, delivery, returns/settlement execution) are not made complete by these four frames.

### Policy Matrix

| Item | Status |
|---|---|
| Cash | TECHNICAL_GAP / POLICY_REQUIRED / ACCESS_REQUIRED |
| Cheque | TECHNICAL_GAP / POLICY_REQUIRED |
| Credit | TECHNICAL_GAP / POLICY_REQUIRED |
| Bill / undertaking | TECHNICAL_GAP / POLICY_REQUIRED |
| Allocation | TECHNICAL_GAP / POLICY_REQUIRED |
| Maturity | TECHNICAL_GAP / POLICY_REQUIRED |
| Collection | TECHNICAL_GAP / POLICY_REQUIRED |
| Returns | TECHNICAL_GAP / POLICY_REQUIRED |
| Settlement | TECHNICAL_GAP / POLICY_REQUIRED / ACCESS_REQUIRED |

Readiness UI/auth/read API: IMPLEMENTED. No row is READY_FOR_APPROVAL as a working financial engine; actual organization contract, approved rules and reconciled data are not available to configure or certify it. Required finance decisions remain in the earlier matrix. Secure uploads, immutable customer offers, quantitative delivery/receipt and returns remain independent IMPLEMENT gaps, not silently reclassified as policy blockers.

Release: NO DEPLOY. Production rollback artifact/provenance certification unresolved, recovery unresolved, full product financial/delivery/return closure incomplete. Build/test success is scoped to Source/isolated Preview. Final Supervisor result and cleanup evidence pending below. TOKEN_USAGE: NOT_AVAILABLE.

Final S7/S8 independent QA: PASS for scoped Source/isolated-preview case workflow and finance-readiness behavior; overall baseline/release BLOCKED. Reviewer inspected actual build/migration/persistence/browser JSON and sequential scripts, without repeating passing tests. Remaining limits: dependency symlink was not OS-enforced read-only (deviation from S7 precondition; dependency immutability NOT_VERIFIED, no damage inferred); duplicate-click scenario used two synchronous DOM clicks; mobile transition pointer click required centered instant test scrolling. Default smooth-scroll interaction is not independently certified. Figma is visually reviewed reference alignment, not pixel-perfect certification.

Cleanup completed with PID/start-time/cwd identity and saved container ID/task-label checks (`cleanup.json`): only this task's3187 Next process and isolated API containers removed; transient test DB and synthetic session-token file removed. No cleanup by port/cwd alone. Both test ports and3062/3063 have no listeners afterward. Source build/evidence remain in `/tmp/60online-s7`; no Production services restarted, no financial data moved. Final production candidate rollback certification remains BLOCKED.
