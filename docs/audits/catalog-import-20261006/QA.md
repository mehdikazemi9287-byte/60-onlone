# Aria / Pouya PDF import checkpoint

Source branch `phase234-20260906T204535Z`, HEAD `9d06e4dbe6cf9a065ad87834e87a761396949a86`. Existing dirty ownership recorded in checkpoint.json. Task edits are two new importer scripts, this evidence directory, a private candidate directory, and three exact Aria PDF PNG assets. No existing application file changed by this import task. No commit, migration, service replacement, routing change, or Production write.

## Result and limits

Five original PDFs: 121 pages; 513 product occurrences. Aria: catalogue 164 occurrences / 162 codes, consumer list 182; 234 identities after reconciling 112 exact supplier-code repeats. Candidate: 223 new Aria masters/publications, zero existing updates. Eleven Aria and 167 Pouya identities retain full source data in the existing external_product_mappings model, pending review. Pouya: veal 43, lamb 62, chicken 62; 162 explicit codes and five code-less descriptions; fresh/frozen cut variants preserved. Generic existing Pouya masters were not merged into specific cuts.

The current master schema forbids NULL unit and package_quantity. Pouya supplies neither, and nine Aria catalogue-only identities lack them. No defaults were fabricated. Source SKU 8033 denotes two square angles; source SKU 9030 has conflicting gross weights. Both identities are quarantined, with original alternatives retained. No unresolved source identity was published. Category is books-stationery for every new Aria master/publication; Pouya retains the existing species categories in staged rows.

All 176 explicit consumer price integers are preserved verbatim with price type and PDF/page provenance. The source lacks a verified currency label or price basis: currency/basis remain NULL; no conversion, supply-cost inference, seller offer, inventory, or sale price was introduced. Source carton quantity is explicitly labeled as such in master specifications; retail pack quantity remains NULL. Supplier names are retained in provenance/identifier issuers; no unverified legal/national-ID account was invented.

Three native embedded photographs were visually matched to SKU 4071 / 1010 / 1011; 398 catalog identities have no image. Three clipped trial crops were rejected and removed, replaced with the native images. No generic or unrelated image entered data. Existing image assets remain intact. Some catalogue descriptive attributes remain in verbatim page text/OCR context rather than validated structured fields; do not claim complete attribute normalization.

## Actual verification

- candidate-qa.py: PASS on existing-schema candidate and disposable clone; every pre-existing row in every table preserved; exact expected insertions only; SQLite quick_check and foreign_key_check pass.
- First confirmed import: 223 masters, 223 supplier identifiers, 223 inquiry-only publications, 401 provenance mappings. Second confirmed import: zero insertions; 401 identities skipped. Both journals and plan digests are private under data/catalog-import-20261006. No offer or stock mutation.
- All 223 new PDP API responses PASS: null price, null available quantity, purchasable=false; offer endpoint empty. Authenticated master lookup PASS 223/223 using an explicitly synthetic user in a disposable QA copy only.
- Organization item validation PASS 223/223 Aria master references with explicit source units and null estimates in a rolled-back synthetic request. End-to-end UI catalog selection BLOCKED: Source organization form uses free text, Pouya remains staged. Pack selection BLOCKED: Source Pack Builder is inactive and backend selection implementation is absent.
- Listing/search/category/pagination PASS: 768 public products including 223 Aria, no repeated product IDs across pages, search Aria returns 223. Public page_size maximum is 48; unsupported sizes are rejected, not silently concealed.
- Rollback PASS on disposable copy: hides precisely 223 created publications and preserves masters/provenance; refuses independently edited after-images. Original candidate and Production were not rolled back.
- Current Source frontend src hashes exactly match isolated build inputs. Next build PASS with type/lint checks. Browser PASS: Homepage, stationery listing, Aria search, exact-image PDP, no-image PDP, organization entry, each at 390px / 1440px. HTTP 200, RTL, no overflow/broken images/page errors. Homepage cards stay nonempty despite 220 new image-less public products. Screenshots visually checked for mobile Homepage and desktop exact-image PDP. ui-qa.json records actual checks; this is basic anonymous rendering, not authenticated purchase/selection QA.

## Environment / API contract

Production public API remains port 8063, frontend 3067; canonical release SQLite path was inspected read-only. Candidate uses the same existing schema snapshot, not a new catalog schema. Loopback QA API 3296 accepts GET/HEAD/OPTIONS only; isolated compiled Source frontend 3295 proxies to it. Public routes /api/v1/products, /products/<slug>, /categories need no authentication; master /catalog routes require JWT. API presentation uses title_fa, purchasable, quantity_available, NULL money, and structured 422 errors. No fallback concealed these contracts. Currency IRR in public publication configuration is existing display configuration, not a verified PDF price currency; provenance keeps source currency NULL.

Source, private candidate, QA preview and Production are distinct. No Production deployment parity or complete catalogue import is claimed. Promotion must use the deployment/import safety process, fresh database backup and after-image rollback journal. Full promotion remains blocked by required-field gaps and source conflicts. Rebuilding the Production master table to allow NULL is a destructive migration requiring explicit concrete approval.

Next: prepare nullable unit/package support in the existing product model and a reviewable migration, preserving existing records; then resolve the two source-code conflicts before full import promotion.
