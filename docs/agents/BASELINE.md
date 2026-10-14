# Read-Only Bootstrap Evidence

Observed 2026-09-15 UTC. This is a dated inventory, not executable configuration.
Refresh relevant entries before using them for future work. No application, DB,
service or production configuration was changed during this bootstrap.

## Identity and Source

- PROJECT_ROOT: `/home/ubuntu/60online-authoritative`.
- README identifies `60online`; homepage explicitly identifies 60Online.
- Server hostname: `ubuntu---2-vcpu---8-gb-ram` (Linux systemd/Docker host).
- Branch: `phase234-20260906T204535Z`.
- HEAD: `9d06e4dbe6cf9a065ad87834e87a761396949a86`.
- Initial and immediately pre-edit `git status --short`: empty (clean).
- Frontend: `frontend/`, Next.js 15.5.25, React 19.1.9, TypeScript;
  `frontend/src/app`, client `frontend/src/lib/api.ts`.
- Backend: `backend/`, Flask 3.1.3, factory `backend/app/main.py`,
  `/api/v1` blueprints under `backend/app/api/v1`, services and DB abstractions.
- Naming discrepancy: frontend package and some backend identifiers retain
  `70online`. No rename was made; naming alone is not project identity evidence.

## Proven Runtime Mapping

`/etc/nginx/sites-enabled/default` names `60online.ir`, `www.60online.ir` and
`95.38.183.168`, listening on port 80. Its `/` and exact `/api/assistant` routes
target `127.0.0.1:3067`; `/api/` targets `127.0.0.1:8063`.
These are on-host routing observations; public DNS/TLS were not audited.

| Runtime | Observed location and port | Classification |
| --- | --- | --- |
| Nginx | `/etc/nginx/sites-enabled/default`, port 80 | Production ingress configuration |
| `60online-prod-green3.service` | `/home/ubuntu/60online-prod-green3/frontend`, Next start 3067 | Current ingress frontend target |
| `60online-bluegreen-api` | image `60online-authoritative-backend:9d06e4d`, container `/srv/backend`, host 8063 -> 8000 | Current ingress backend target |
| Backend data mount | host `/home/ubuntu/60online-release-backups/20260906T204535Z/bluegreen` -> container `/blue` | Live writable mount; not merely a backup despite its parent name |
| Backend DB setting | `sqlite:////blue/70online.db` | Host DB path resolves to the mount above plus `70online.db` |
| `60online-prod-green.service`, `60online-prod-green2.service` | corresponding `60online-prod-green/frontend` and `60online-prod-green2/frontend`, 3065/3066 | Running alternatives, not current Nginx frontend target |
| `60online-staging-fe.service`, `60online-stg2-api` | staging-work frontend 3064, API 8064 with staging-work/stage2 mount | Named staging; full isolation not audited |
| `60online-phase234-api`, `60online-candidate-backend` | 8062, 8051 | Running alternatives; RC status unverified |
| `70online-production-backend-1`, `70online-production-frontend-1` | 8000, 3000 | Legacy-named containers, not current Nginx targets |
| `60online-ui-test` | 3001 | Preview-named container, QA status unverified |
| `60online-storefront.service` | `/home/ubuntu/70online/repo/frontend/server.js --root dist` | Running legacy storefront |
| `60online-ai`, `60online-search`, `60online-meili` | 3070, 3068, container-only 7700 | Running related services; production dependency chain not audited |

Legacy backend Compose labels point at `/home/ubuntu/70online/repo`,
`docker-compose.production.yml` and `/tmp/60online-no-migrate-20260903.yml`.
Those labels do not establish the active production backend's compose source.
Additional listeners include 3010, 3050, 3051, 3062 and 3063; exact ownership and
environment classification were not established. No certified RC was identified.
There is no proven single production source root: frontend is a separate working
directory, backend is an image, and DB is a separate mount. Image tag similarity
to HEAD is not byte-level proof that the deployed backend equals this checkout.

## API and DB Evidence

- Read-only GET through local Nginx with `Host: 60online.ir`:
  `/api/v1/health/ready` -> HTTP 200,
  `{"expected_version":"0028","schema_version":"0028","status":"ready"}`.
  Endpoint source checks DB reachability and migration metadata. This proves
  observed readiness only, not supplier/product/price/stock/image correctness.
- GET `/` through the same ingress -> HTTP 200. Visual/interaction QA not run.
- Frontend browser client defaults to same-origin `/api/v1`.
- Source Next API proxy and `server-catalog.ts` default to port 8000 when
  `BACKEND_INTERNAL_URL` is unset; current ingress API targets port 8063.
- Current frontend systemd unit explicitly sets
  `BACKEND_INTERNAL_URL=http://127.0.0.1:8063`, resolving that default-origin
  difference for its server requests. Other runtime overrides and complete
  request/response contract parity were not audited.
- Production routes `/api/assistant` to Next; that handler is absent from this
  checkout's enumerated API routes. Source/runtime parity is not established.
- No direct DB writes, seeds, migrations, app startup, builds or restarts ran.

## Protected Areas and Previous Baseline

Historical manifest:
`/home/ubuntu/60online-release-backups/20260906T204535Z/manifest.json`.
Its base commit is `96c03d02aa8a2a1134043c66425988c1c32c4aea`.
Current Source protected files match its recorded SHA-256 values:

| File relative to frontend | Source and historical manifest SHA-256 |
| --- | --- |
| `src/app/page.tsx` | `b8705de1f008387f083f94213666948b3ebf3b055c0a5d15fb28db3123b5034e` |
| `src/components/home/PackBuilder.tsx` | `113bd7b70e87d6e6918849260cbfd5c0d003e3c47db3c73afcc8235481ad2df9` |

The corresponding production-directory files differ:

| File relative to production frontend | Observed SHA-256 |
| --- | --- |
| `src/app/page.tsx` | `5897410c56aadb94dba01973900f58ae4440c6d401908f74564dc0feba3fc5c0` |
| `src/components/home/PackBuilder.tsx` | `d85cb18c350adfb8d570e563023df2dad7511355319fd674f11ca6318c1ff8dd` |

Source Homepage imports PackBuilder and includes it in `/`. Source PackBuilder
is an explicit unavailable-feature notice. The production-directory wrapper
imports `PackBuilderInteractive.tsx`. Preserve both versions; do not restore the
old version into production or claim their UI/UX is equivalent. Production source
inspection alone does not prove which bytes are in its built Next artifacts.
Protection also covers global styles, layouts, shared components and other
dependencies that can alter either area's UI/UX. This is an agent policy guard,
not a claim that CI or filesystem enforcement already exists.

Historical `backend-final-green.log` reports 1425 tests, OK with 2 skipped;
`backend-final-image.log` records image tag `60online-authoritative-backend:9d06e4d`.
Earlier `backend-final-tests.log` reports 155 failures and 24 errors. These are
historical records with differing outcomes, not new test runs or proof of current
release readiness. No full audit or full application test suite was repeated.

## Framework Provenance and Limits

No existing AGENTS.md or Karen Travel framework was found in the bounded search
under `/home/ubuntu`, `/opt`, `/srv` (depth 4); ancestor policy paths were checked.
The exact Karen Travel standard is therefore unavailable and equivalence cannot
be certified. This framework implements the user-specified Supervisor/seven-role
architecture and all 20 supplied 60Online rules without importing another
project's configuration. Exact comparison can be performed when that reference
becomes available; this does not block the authorized documentation bootstrap.

Roles defined: Master Supervisor, Backend, Frontend, QA, DevOps, Security,
Research/Integration. No worker agents or background services were launched.
