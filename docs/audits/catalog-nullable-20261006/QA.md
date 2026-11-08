# Nullable unit / pack and staged import delta

Continues docs/audits/catalog-import-20261006/QA.md without re-extraction. Branch phase234-20260906T204535Z, HEAD 9d06e4dbe6cf9a065ad87834e87a761396949a86. Initial dirty status/hashes in checkpoint.json; owned deltas in manifest.json. Existing unrelated visual, organization and backend work retained. User explicitly authorized existing Pack Builder and organization selection changes. No Production writes, deployment, routing change, restart, migration, commit or push.

## Final candidate

Aria 234 identities: 233 imported, zero valid staged, one quarantined. Pouya 167: all imported (43 veal, 62 lamb, 62 chicken), zero staged/quarantined. Delta creates 177 master/publication records: nine formerly missing Aria unit/pack, 167 Pouya, one resolved 8033. Existing 223 imports remain unchanged. Full catalog integration uses the same master_products, publications, identifier and external mapping tables. All 401 mappings remain unique; 400 imported masters and one pending conflict; no parallel runtime catalog or duplicate products/offers.

NULL units/packages: nine Aria + 167 Pouya = 176; real populated values preserved. All 176 raw consumer prices remain in original source metadata with currency/basis unconfirmed. Final sale prices NULL for all 400 imported products; no new offers, inferred inventory or purchasability. Three verified original embedded Aria PNGs unchanged; 398 source identities lack an image, including the quarantine (397 imported masters without an image). Three clipped trial crops remain rejected. No image generation/enrichment or generic replacement.

## Migration / rollback

0043 integrates into existing migrator, with the SQLite implementation bound to a SHA-256 in the SQL artifact. SQLite cannot ALTER COLUMN DROP NOT NULL: canonical master table reconstructed atomically, with original table retained as _rollback_0043_master_products, solely for rollback. No DROP or DELETE; existing row values, IDs, foreign-key targets, constraints other than unit/pack requirements, and indexes retained. Defaults removed, positive-pack CHECK retained. Backup data/catalog-import-20261006/before-nullable.db is private and ignored by Git. Candidate only.

Migration PASS: null insert, existing value preservation, second-run no-op, FK/quick_check, guarded pre-import constraint rollback and refusal after later master writes. Constraint rollback retains forward table and migration ledger for audit, and is an operational reversal rather than a rerunnable migration. After import retain nullable schema; hide new publications using exact after-image journals. Post-import visibility rollback PASS for all 177 delta publications on a disposable clone, deleting zero masters/provenance. Database snapshot restore is not performed and would require separate approval. PostgreSQL equivalent ALTER statements prepared; NOT_RUN because current target is SQLite.

No raw schema text mutation, invented defaults, schema initialization or migration as an inspection shortcut. Archive is not referenced by catalog/API queries. Updated NULL paths detailed in nullable-paths.md.

## Conflicts

Resolved original 8033 conflict by visual review ONLY of original page 78. The left 60° caption explicitly prints 8032; right 45° prints 8033, matching newer consumer-list identity. Original extraction incorrectly assigned 8033 to both. Historical extraction evidence retained; reviewed-rows.json is the corrected delta. Source changes require reviewed old-metadata digests and journal before-images. 8032 gets only provenance enrichment; verified master values unchanged. 8033 is now imported.

9030 remains quarantined: pages 96/97 display different animal-scissors assortments, dimensions 114×80×1 versus 233×135×140 mm and product weights 50 versus 1500 g, both printed code 9030 and carton count 112. No reliable alternative SKU or existing verified supplier mapping proves identity. Do not merge or invent variant identifiers; supplier confirmation required. conflict-review.json records precise evidence. No other PDF page processed.

## Selection contract and verification

Existing /api/v1/catalog/selection public projection exposes only already-published active masters, with search/SKU, exact existing category, source-supplier filters and bounded pagination. Returns real master IDs/attributes/nullable unit and package quantity; request selection true, sale price/stock NULL and purchasable false. No private/draft master or customer data exposed. No registry supplier account invented from source name.

Shared RequestProductPicker supports exact product/variant master selection, quantity, removal, pagination and filters. Existing homepage PackBuilder holds request selections and hands them via sessionStorage to /org. Existing organization form creates master-linked purchase requests with explicit nullable unit and NULL estimate, then existing submit/approve/RFQ routes. Approved request exposes RFQ creation. No checkout, automatic pricing, stock inference or new pack/catalog architecture. Existing org intake no longer fabricates/mandates a unit; malformed non-null empty strings remain rejected. Existing quantity/auth/organization/approval rules retained.

Actual final QA (supervisor performed separate local reviews and final QA; no independent reviewer claimed):

- PYTHONPATH=backend /tmp/60online-pdf-parser/bin/python -m unittest backend.tests.test_catalog_nullable_candidate backend.tests.test_organization_intake backend.tests.test_organization_operations -v: PASS, 16 tests. Private disposable SQLite copies or explicitly synthetic seeded fixtures only, no test sales override in candidate QA. Tests cover all 400 imported PDPs, preservation of every original master, NULL/invalid pack/unit validation, source-price counts, exact mapping counts, species/supplier/category/SKU filtering, pagination, null-unit request/approval/RFQ E2E, request replay, no direct cart purchase, authentication and existing organizational permission regressions.
- Unrelated table rows match pre-nullable snapshot exactly (data-qa.json): no business data changes outside approved catalog/mappings. Schema changes limited to canonical master constraints/defaults, rollback archive/index copies and migration ledger.
- Second confirmed import after conflict correction: PASS; 401 identities skipped, zero insertions/updates, private journal empty. Plan/result digests retained.
- Next frontend build in /tmp/60online-premium-build: PASS compilation/type/lint checks; every src input hash matches current Source. No production build/deployment claim.
- Playwright Chromium at 390px and 1440px: PASS supplier/category/SKU picker filters; unknown-stock/null-price products selectable; quantity 3 handoff from existing pack to organization; two real imported master items per request; null unit and null estimate; submission/approval/RFQ creation; all selected references and quantities preserved. Anonymous/public selection and authenticated synthetic member browser flows use real candidate backend contracts, no intercepted/mock responses.
- Homepage, poultry listing and Aria search PASS at both widths: populated product cards, RTL, zero overflow/broken images/page errors. Pouya PDP renders استعلام قیمت; all 400 backend PDPs null-sale-price/inquiry-only. Mobile organization screenshot visually inspected. ui-qa.json and screenshots contain synthetic QA organization records only.
- Exact-image reuse, syntactic/whitespace checks and final status recorded; no images changed in this delta.

Loopback preview frontend 3295, backend 3296 used a disposable candidate copy with explicitly synthetic browser organization/user; separate private candidate data is not modified by browser requests. Preview processes stopped after QA. Source, candidate, preview and Production remain distinct. Only the SQLite candidate is verified; release-package/runtime promotion rehearsal is not performed. READY_FOR_PRODUCTION=NO for complete-catalog release while 9030 remains unresolved; no production authorization implied.

Next: obtain supplier-confirmed identity/variant codes for the two 9030 catalogue assortments before full release promotion.
