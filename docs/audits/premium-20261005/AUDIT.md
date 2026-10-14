# Premium transformation — source scope, 2026-10-05

Root `/home/ubuntu/60online-authoritative`; branch `phase234-20260906T204535Z`; HEAD `9d06e4dbe6cf9a065ad87834e87a761396949a86`. Existing backend/procurement, organization/operations pages, releases, data and documentation are owned by prior work and must be preserved. This task owns only the visual changes listed in the final report and this evidence directory.

User explicitly authorizes homepage and Pack Builder visual work, preserving architecture, backend, routes and business behavior. No deployment/reload/restart or DB mutation authorized. Local supervisor performs design, integration review and a separate final QA pass; no delegated agents.

## Read-only reality

Current Nginx ingress remains frontend 3067 / API 8063. GET `/api/v1/health/ready`: HTTP 200, schema and expected version **0042** (dated baseline had 0028). Public catalog pagination inspected via GET: 545 products, 82 image URLs, 0 non-null sale prices, 0 purchasable products. Evidence: `catalog-evidence.json`. Source normalization maps flat title/category/brand/stock fields to presentation types; lists map `total_pages` to `pages`. Rial values display in toman /10. No new currency, stock or pricing assumptions introduced.

Source browser API defaults same-origin `/api/v1`; source SSR/proxy default 8000 differs from production ingress API 8063. Isolated preview explicitly uses 8063; this does not prove release parity. Authenticated cart requires Bearer token; no authenticated mutations tested. Error envelope handled as `{error:{code,message,details}}`. Missing media, ratings and specifications remain absent. Pack/bundle route search in this source found no supported pack contract. Source Pack Builder is unavailable; production-directory interactive implementation differs historically. No copy-over of production implementation.

## Visual audit and direction

Existing UI: inconsistent radii and surface tokens, heavy decorative gradients/shadows, repeated borders, oversized status treatments, product cards with reserved empty rating rows, hidden desktop wishlist controls, buttons nested inside product links, small touch targets, and no global reduced-motion handling. PDP uses a single valid source image; additional angles/specifications must not be fabricated. Homepage section order, category destinations and product listing remain intact.

Direction: quiet warm-white surfaces, ink/navy typography, restrained blue primary actions, coral as a small accent, generous section rhythm, image-first media and clear intentional quote states. Tokenize typography, spacing, radius, elevation and motion. Preserve RTL and allow Persian names/prices to wrap. Keep media contain; do not recolor, stretch or regenerate product packaging.

Image enhancement is limited to presentation until source/provenance and adequate reference material support destructive pixel transformations. Originals stay unchanged; no fake promotional renders. No gallery beyond the available front image. No image optimization proxy dependency added without verifying asset hosting. Figma requested skills loaded; no Figma reference/file supplied, no Figma writes performed. Adobe capability unavailable.

## Regression plan

Before/after source screenshots: homepage, catalog, valid-image PDP, category and unauthenticated organization entry. After checks: widths 390/430/768/1024/1280/1440, RTL, DOM overflow, broken images, keyboard focus, media failure, API failure/empty states and reduced motion. Public image paths in the preview route to current ingress for GET only. Preview at `/tmp/60online-premium-preview`, loopback port 3295, API mutations blocked in its temporary proxy. No preview database or service startup. Build and TypeScript checks occur only in this isolated copy. Dev-server performance measurements cannot certify production LCP.

## Contract-dependent gaps

Live budget/remaining budget, saved packs, bulk add, completed-pack state, organization pack count/value/eligibility and real pack compositions need a verified server contract. Keep the unavailable state intentional; do not simulate enabled controls or invent packs. Public product API lacks verified gallery, variants, specifications and eligibility fields. Their absence is a data/integration gap, not permission to add sample business data.

## Availability presentation correction

Backend research/no-offer rows report `in_stock:false` and `quantity_available:null`. Existing normalizer maps this to `stock:0`; homepage cards then claimed sold-out inventory, although this response does not establish actual warehouse stock. CatalogBrowser already suppresses stock for nonpurchasable rows and PDP also does so. Shared cards now only show quantity/sold-out stock labels for purchasable products; quote-only rows keep the quote presentation. Price, purchasability, API mapping and cart behavior unchanged.

## Verified source-image gap resolved

All sampled real backend image URLs were initially absent from source public assets. The public catalog contains 82 image-bearing products sharing 76 unique local URLs. Verified 76 originals against current ingress: 72 existing files matched byte-for-byte and were preserved; four missing originals were added at their exact source paths. No existing different file overwritten. PNG, JPEG and WebP magic checked; SHA-256, byte size, URL and retrieval source recorded in `image-provenance.json`. Total originals: 53,480,018 bytes. Source Next/Sharp installation was verified before enabling local image optimization; responsive `sizes`, quality 85, WebP negotiation, lazy cards and priority PDP now use the established optimizer. No processed files replace originals. External future URLs retain native image presentation rather than assuming an unverified allowlist. Final screenshots use source assets directly, unlike the explicitly routed before baseline.

Final QA environment supersedes the early development preview: production-mode Next build from `/tmp/60online-premium-build`, loopback 3295, public API GET target 8063. Source CSP stays intact. No database/services initialized; no authenticated write request sent.

## Refreshed production path mapping

`systemctl show 60online-prod-green3.service -p WorkingDirectory -p MainPID`: MainPID 1611824, WorkingDirectory `/home/ubuntu/60online-authoritative/releases/20260929-visual/frontend`. This supersedes the dated green3 path in BASELINE.md; current ingress port 3067 remains unchanged. Release homepage/public catalog paths resolve inside that release; owned source paths resolve inside `/home/ubuntu/60online-authoritative/frontend`. Source sits on root ext4 with no separate mount. No release files, production compiled artifacts or service/routing settings changed. A release directory name is not proof of release readiness or deployed revision.
