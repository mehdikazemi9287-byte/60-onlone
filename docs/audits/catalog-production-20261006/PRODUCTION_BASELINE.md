# Production baseline — 2026-10-06T14:45:54Z

VERIFIED_CATALOG_READY: PASS — 233 ARIA + 167 POUYA published; 400 final-sale prices null, inquiry selection enabled, no direct purchase or fabricated stock.
QUARANTINED_ITEMS: 1 — ARIA SKU 9030, BLOCKED_IDENTITY / SUPPLIER_CONFIRMATION_REQUIRED; excluded from Production.
IMAGE_ENRICHMENT_PENDING: 398 source identities (397 published + 1 quarantined); 3 exact images served and hash-verified. Missing images do not block catalog readiness.

Production is the actual nginx ingress on this server: API 8065, frontend 3069. Previous services 8063/3067 remain available for rollback. API APP_ENV retains its pre-existing staging value; ingress and the canonical live database establish Production identity.
API image: sha256:41603e27f11169d249f97c8665b00fe73a55c521163faa8e9c3843e779223928
Frontend build: 35_r0I3gdTVThzZ3qmmA4; service enabled.
Database: releases/20260925-canonical/data/70online.db.
Migration 0043: nullable unit/package_quantity; all existing master values preserved. Reviewed migration rehearsal preceded live apply; post-apply integrity/FK and nullability verified.

Counts: {"master_products": 1039, "products": 560, "suppliers": 12, "seller_offers": 489, "catalog_publications": 903, "external_product_mappings": 400, "users": 24, "organizations": 1, "purchase_requests": 0, "rfqs": 0, "orders": 10}

Current Production QA evidence:
- production-data-qa.json: original catalog rows unchanged, 400 distinct identities, zero duplicate/conflicting published SKU mappings, 9030 absent; rollback hides exactly 400 publications on disposable clone.
- production-http-qa.json: 400 live PDPs, null final price, request_quote CTA, sales disabled; supplier searches and all 3 exact image hashes verified.
- production-ui-qa.json: real nginx Production desktop 1440/mobile 390; Homepage, search, PDP, organizational picker, RFQ creation and existing Pack Builder request selection PASS. No page errors/overflow/broken images.
- production-idempotency.json: second import against the live DB skipped all 400; zero writes.
- temporary-qa-cleanup.json + production-final-state.json: owned test user/org, 4 PRs, 2 RFQs and exact descendants removed; business counts restored to their original values. Two temporary auth audit rows removed inside a locked transaction with exact append-only triggers restored before commit; unrelated audit rows preserved.
- backup-qa.json: full online DB backup restore-tested on disposable target; complete previous frontend/image/routing/service backups retained privately. Fresh immediate pre-migration online backup also retained.

Rollback: sudo -n python3 releases/20261006-catalog-verified/rollback.py. Guards exact publication after-images and current routing, hides only imported publications, restores previous routing, preserves masters/provenance/customer data and nullable schema. Full backup restore is separately available; no live restore overwrite performed.

Backend regression: 17 targeted tests PASS before deployment; current Production E2E proves actual contracts. Protected Homepage source and HomeSections remain byte-identical to previous Production; existing Pack Builder adapted only for actual nullable request units.
No commit/push. Existing unrelated working-tree changes preserved. Final git diff --check PASS.

NEXT: Obtain supplier confirmation of SKU 9030 identity; re-review only that quarantined identity.
