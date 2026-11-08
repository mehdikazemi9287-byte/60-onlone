# 60Online Agent Policy

Applies to this repository and every task performed for it. Read this file first,
then `docs/agents/WORKFLOW.md` and only the relevant roles in
`docs/agents/ROLES.md`. Use `docs/agents/BASELINE.md` as dated evidence, not as
permanent deployment configuration. Resolve PROJECT_ROOT using
`git rev-parse --show-toplevel`; never copy another project's paths or settings.

## Mandatory Rules

1. Backend, Data and Integration take priority over frontend work.
2. The server is authoritative. A Mac is only a management interface; its files,
   services and data do not establish server or production truth.
3. Never fabricate data, implementation status, evidence or verification.
4. Homepage is protected: `frontend/src/app/page.tsx` and its dependencies.
5. Smart Pack Builder is protected: `frontend/src/components/home/PackBuilder.tsx`,
   related implementations such as `PackBuilderInteractive.tsx` in deployment
   copies, and its dependencies.
6. Changes to either protected area's UI/UX require an explicit user instruction
   covering that change. This includes indirect changes through global CSS,
   layout, shared components, assets, content, configuration or API presentation.
7. Before changing anything, inspect the actual Backend/API/DB state relevant to
   the task, using read-only evidence. Never initialize an app, run migrations,
   seed a database or start services as an inspection shortcut.
8. Report differences between frontend API assumptions and the real backend:
   origin, routes, authentication, schema, units, pagination and errors. Do not
   conceal a mismatch with fallbacks or claim untested contract parity.
9. Supplier/Product/Price/Stock/Image are real business data. Never replace them
   with mocks, invented values or placeholder images. Isolated synthetic test
   fixtures must be clearly labeled and never enter runtime business data.
10. Preserve others' existing changes. Never overwrite, revert, reset or clean
    them. Record ownership and restrict edits to the agreed scope.
11. Production deploys, restarts, reloads, image/service replacement and routing
    switches require explicit user approval for the concrete operation.
12. Destructive DB operations require explicit user approval. Treat drops,
    truncation, deletion, destructive migrations and restore-overwrites as such.
13. Check `git status --short` before and after every task, including delegated
    tasks. Record branch and HEAD when establishing the task baseline.
14. Reuse a verified previous baseline. Distinguish historical test success from
    current verification; never restore an older baseline over newer work.
15. Use targeted inspection. Do not repeat full audits without a concrete reason.
16. Minimize tokens: narrow searches, bounded output, concise evidence and handoffs.
17. Activate only necessary agents. Role definitions do not launch processes or
    grant authority. Avoid delegation for work that is cheaper to do locally.
18. QA is the final gate after implementation and all other role reviews. Any
    subsequent edit invalidates the applicable QA result until rechecked.
19. Every PASS needs actual verification: command/check, target, result and scope.
    Use FAIL, BLOCKED or NOT_RUN honestly. A healthy endpoint is not product QA.
20. Keep Source, Preview, RC and Production distinct. A folder name or image tag
    alone does not prove an environment, a deployed revision or release readiness.

## Supervision

Master Supervisor owns scope, task routing, evidence and reporting. Backend owns
server contracts and data behavior. Frontend consumes verified contracts. DevOps
owns environment mapping; Security reviews relevant risk; Research/Integration
validates external sources and connectors. QA closes the task using real evidence.
Detailed boundaries and handoff fields are in the linked role/workflow documents.

No agent may approve its own production or destructive DB operation. Prepare a
reviewable result within authorized scope, then obtain any required explicit
approval. Do not commit, push or deploy merely because a task passed QA.

The bootstrap is documentation-only. It does not authorize changes to application
code, DBs, services or Production, or changes to either protected area's UI/UX.
