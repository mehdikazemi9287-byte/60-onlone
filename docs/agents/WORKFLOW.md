# Task Workflow

## Intake and Read-Only Preflight

1. Read root policy. Run `git rev-parse --show-toplevel`,
   `git branch --show-current`, `git rev-parse HEAD`, `git status --short`.
2. Identify the requested outcome, allowed files/actions, environment and explicit
   approvals already given. Record protected UI/UX impact, including dependencies.
3. Reuse `BASELINE.md` and relevant existing evidence. Refresh only facts needed
   for this task or likely to have changed. Do not treat an old source checkout
   as the current production release.
4. Inspect relevant Backend/API/DB reality read-only. Prefer known safe readiness
   endpoints and schema metadata. Do not import startup code with side effects or
   open a live SQLite DB using settings that create/write files. Never expose
   credentials, user records or entire environment dumps.
5. Record contract discrepancies and unknowns before implementation. Choose only
   necessary roles and give each a bounded contract with owned paths.

## Implementation and Final Gate

1. Make only authorized changes, preserving dirty work. Source/Preview changes
   must not implicitly alter Production through mounts, symlinks or services.
2. Report newly discovered API/DB or protected-area conflicts; do not work around
   them with invented data. Continue independent authorized work where possible.
3. Run scoped verification in an isolated environment when application tests are
   needed. Confirm test DB/service isolation before execution. Do not run a suite
   against Production or reuse production credentials as test configuration.
4. Complete Backend/Integration, Frontend, DevOps and Security reviews as relevant.
5. QA runs last: review actual changed paths/diff, protected impact, acceptance
   criteria and evidence. Run `git diff --check` and final `git status --short`.
   Explicitly inspect new untracked documentation; ordinary `git diff` omits it.
6. Report results and material limitations. A production release remains a
   separate explicitly approved operation, even after QA succeeds.

## Environment Definitions

| Environment | Evidence required |
| --- | --- |
| Source | Git root, branch, HEAD and dirty state; no implied runtime parity. |
| Preview | Exact process/service, path, port and isolated data target. |
| RC | Explicit candidate revision/artifact, configuration/data target and applicable QA evidence. Not inferred from a candidate-like name. |
| Production | Actual ingress routing plus runtime process/container and mounts; verify deployment provenance separately. |

## Task Record Template

```text
TASK / OUTCOME:
PROJECT_ROOT / ENVIRONMENT:
BASELINE_HEAD / GIT_STATUS_BEFORE:
SCOPE / OWNED_PATHS / ACTIVE_ROLES:
BACKEND_API_DB_EVIDENCE:
API_MISMATCHES / UNKNOWNS:
PROTECTED_IMPACT / EXPLICIT_APPROVALS:
CHANGES:
VERIFICATION: check | command or evidence | target | result | limitations
QA_GATE:
GIT_STATUS_AFTER:
PRODUCTION_CHANGED:
NEXT_ACTION_OR_BLOCKER:
```

For bootstrap summaries include STATUS, PROJECT_ROOT, SERVER, PRODUCTION_PATH,
SERVICES, PROTECTED_AREAS, AGENTS_DEFINED, FILES_CHANGED, GIT_STATUS,
PRODUCTION_CHANGED and READY. Qualify READY by scope; never imply release approval.
