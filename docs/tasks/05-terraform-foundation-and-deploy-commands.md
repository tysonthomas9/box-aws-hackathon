# Terraform foundation and deploy commands

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `767193d8-5975-42ab-940c-9fccad204285`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

All phase 1 AWS resources defined in Terraform, with one-command deploy and destroy.

## Scope
`infra/` Terraform, S3 state backend created by `make bootstrap`, region **us-east-2** only. S3 buckets (artifacts, web); DynamoDB tables (items, reviews, versions, ask jobs, sync cursors, webhook dedupe with TTL); Secrets Manager: reference the existing `box-hackathon/box-ccg` (don't recreate it), plus new entries for Box webhook keys and the shared password (values set out of band); least-privilege IAM roles (each Lambda, Step Functions, SageMaker execution, Bedrock import role); API Gateway HTTP API (default endpoint disabled, reached via CloudFront); CloudFront with /api/* forwarded (no cache, cookies forwarded) and the static site; EventBridge Scheduler (1 min sync); Lambda functions from `lambdas/` (zip via uv, or container images if dependencies require); Step Functions resource (definition supplied by the training task); CloudWatch log groups with 7-day retention. Tag everything project=box-hackathon. Variables: name prefix. Makefile: `bootstrap`, `build`, `deploy` (apply + upload web + print URL), `destroy` (runs the cleanup ledger for Bedrock imports and the Box webhook first). No AWS Budgets resource (Budgets is global; skip unless Tyson asks).
Not in scope: application logic.

## Definition of Done
`terraform validate` and `terraform plan` clean; `make deploy` creates the stack with placeholder Lambdas responding through CloudFront; `make destroy` removes everything.

## Verification
`make bootstrap && make deploy`; curl `<url>/api/health`; `make destroy`.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Keep the API Gateway default endpoint enabled** (disabling it needs a custom domain). CloudFront adds a secret origin header that the API checks; the app checks cookies itself.
- CloudFront /api/*: managed CachingDisabled + AllViewerExceptHostHeader (forward cookies, query strings, Origin and Box signature headers).
- **Ask worker resources:** SQS queue + worker Lambda (long timeout) + DLQ, with permissions; the Web app task supplies the code.
- **Cleanup ledger owner:** a DynamoDB ledger table and a small shared interface (record before or around creation, reconcile uncertain outcomes); `make destroy` consumes it first. "Nothing left" means deployment-owned resources only; pre-existing POC resources are preserved.
- **Package-size gate in this wave:** build the Linux Python 3.12 API/sync artifact (FastAPI + Mangum + box-sdk-gen), measure the unpacked size and cold import time; use a container image if it's near 250 MB. No torch/transformers in Lambdas.
- Step Functions and Lambda code start as explicit placeholders; the integration deploy happens in wave 4.

## Implementation progress — 2026-10-17

Read full review overrides. Ownership: infra/, scripts/infra*, lambdas/placeholder.py, kloop/cleanup.py, tests/test_cleanup.py, additive Makefile and .gitignore. Existing answer-smoke target will be included in the coordinated Makefile commit. Bootstrap private/versioned/encrypted state succeeded for owned prefix kloop-wave2; terraform validate and plan passed. Five cleanup safety tests pass. Linux Python 3.12 x86_64 API/sync artifact initially 36.6 MB unpacked; pinned/hash-locked build added and live cold-import probe is next. Coordinator explicitly approved origin guard in state; real secrets stay out of Terraform. Live placeholder deploy started; no imports, training jobs or Box resources created.

## Live gates — 2026-10-17T06:36Z

PASS: bootstrap + 64-resource Terraform placeholder deployment in us-east-2 under owned prefix kloop-wave2; final terraform validate/plan is no changes. Final live smoke: CloudFront static 200, health 200 (explicit placeholder), direct execute-api 403. Linux x86_64 Python 3.12 FastAPI/Mangum/Box SDK cold imports: 1.473 s; initial total Lambda Init Duration 2286.76 ms. Artifact 48,629,206 bytes unpacked / 25,315,666 zipped, SHA256 37da4f4d211bbec12543c9f840ce0a9c702a4682caa887e9b7edb686dbd0ae86, two deterministic rebuilds match; Lambda CodeSha256 matches. Full suite 82 passed; focused cleanup/storage/contracts 20 passed; lint/format/TF fmt clean. Destroy is running, including bootstrap state bucket last. POC import ARNs captured for a before/after preservation check. This proves infrastructure wiring only; application integration remains a later wave.

## Final secret placement correction

Applied coordinator direction received during teardown: webhook signing keys remain out of band in existing box-hackathon/box-ccg JSON fields webhook_primary_key/webhook_secondary_key; no separately owned webhook secret. API and sync roles receive only GetSecretValue on that existing secret. Shared-password auth and cookie-signing secrets are distinct new resources with no Terraform-managed values. The live proof above preceded this final secret topology correction; revised configuration is being independently validated/planned in an isolated local backend without re-creating the proof stack.

## Teardown credential recovery — 2026-10-17T06:47Z

Initial destroy deleted CloudFront after 8m28s but its static exported token expired before S3 state save. No new login needed: existing CLI session refresh works. Recovered only this run’s stale lock after proving no Terraform process remained, then pushed errored.tfstate without force; five managed resources remained. Fixed commands to use a temporary credential_process profile (no credential values in files) so the AWS SDK can refresh throughout long operations. Added a passing regression test that rejects stale inherited credentials, verifies repeated process lookups, and detects recursive profile use. Retrying cleanup of the five remaining resources and then the bootstrap bucket. Final secret correction validates/plans (66 creates in an isolated local planning backend); it was not re-applied during teardown.

## Completed — 2026-10-17T06:49Z

Committed and pushed `891b5a543b50bb961cecfc228a2451de3a89462b` to withered-cobra after successful git pull --rebase. Final make test 85 passed; lint/format/TF fmt/diff checks pass. Independent service inventory confirms zero owned proof-stack resources; both POC imports and existing Box CCG secret unchanged. State bucket removed last after safe state recovery; fixed command credential refresh and partial-destroy resumption, with two regressions passing. Final coordinator-directed secret topology validates/plans (66 resources) but was not re-applied during teardown; live placeholder proof and artifact hashes are separately recorded. PR context appended to note846fb942-136d-4b81-98f2-354a4926f1de. Only own files plus coordinated Makefile additions committed; AGENTS.md/CLAUDE.md and POC files untouched. Task-owned temporary scripts/logs/Terraform binary removed; committed evidence retained in infra/evidence/. No live resources retained.

## Verifier findings — Terraform wave 2, 2026-10-17

### Verification Summary
- Verdict: ❌ NOT APPROVED
- Confidence: High
- Exact reviewed head: 891b5a543b50bb961cecfc228a2451de3a89462b; scaffold base: 14a9d4a54c896116458b97b5301bd4e04fae33e0.
- Scope: task 767193d8-5975-42ab-940c-9fccad204285 only. No repository edits or live deployments. No spec ambiguity.

### Acceptance Criteria Checklist
- ✅ VERIFIED — Terraform resources and declared wave-2 scope.
  - Evidence: 891b5a5 infra/*.tf and bootstrap/main.tf define selected Region us-east-2, private encrypted buckets/state, seven pk/sk tables including ledger and dedupe TTL, per-Lambda roles/logs, training/import roles, HTTP API, CloudFront policies/origin guard, one-minute Scheduler, SQS worker/DLQ, explicit placeholder Lambda/Step Functions code. README clearly defers application runtime permissions to integration.
  - Verification: full static review; Terraform 1.13.4 fmt -check -recursive PASS; isolated local-backend init/validate/plan PASS, 66 creates. Original backend/state untouched.
- ✅ VERIFIED — Final secret topology.
  - Evidence: existing Box CCG data source only; auth/cookie-signing/origin owned secrets; only origin has a Terraform-managed value (accepted state exception). Box keys remain in existing CCG secret. API and sync get scoped Box GetSecretValue.
  - Verification: independently inspected saved final plan JSON (66 creates); no owned webhook secret, no auth/cookie secret versions.
- ✅ VERIFIED — Placeholder deploy and destroy Definition of Done.
  - Evidence: accepted implementor live report and infra/evidence/{placeholder-smoke,verification,cleanup}.json: static/health 200, direct execute-api 403; zero owned resources after teardown, POC imports and existing Box secret preserved.
  - Verification: accepted live proof as assigned; reviewed destroy sequencing, ownership checks, uncertain-create refusal, retry records, and seven cleanup/two command regressions in passing suite. Final secret correction was planned, not live reapplied; full long CloudFront delete was not repeated after refresh fix.
- ✅ VERIFIED — Package gate.
  - Evidence: Linux Python 3.12 x86_64 pinned/hash-locked FastAPI/Mangum/Box SDK artifact; 48,629,206 bytes unpacked; SHA256 37da4f4d211bbec12543c9f840ce0a9c702a4682caa887e9b7edb686dbd0ae86; accepted live cold-import evidence 1.473 seconds.
  - Verification: inspected current archive size/hash and absence of torch/transformers; build stops at 220 MiB.
- ✅ VERIFIED — Scope and no committed secrets.
  - Evidence: Terraform commit contains 23 declared paths, coordinated additive Makefile edits and declared .gitignore ownership; no other task implementation files, no AGENTS.md/CLAUDE.md or POC edits in this commit. Other wave-2 commits belong to other tasks and are excluded from this task verdict.
  - Verification: git show/diff-tree, bounded manual changed-source review and credential-pattern scan found no actual credential literals; git diff --check PASS. IDs/ARNs are references. Three pre-existing untracked files unchanged.
- ⚠️ DEVIATION — Spec: `make test` passes without AWS or Box credentials.
  - What differs: new global Makefile AWS_PROFILE export (lines 18–20) makes offline tests require a locally configured box-hackathon profile.
  - Evidence/repro: normal make test && make lint PASS (85 tests). With AWS config/credentials unavailable, make test gives 2 failures, 17 errors, 66 passes; ProfileNotFound: box-hackathon. Direct uv pytest in the same empty AWS environment passes all 85.
  - Impact: a fresh checkout cannot run the advertised offline test command without AWS setup.
  - Minimal fix: scope AWS_PROFILE export to deployment/cloud targets and keep test/lint independent of local AWS profiles.
  - Re-verify: `env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true make test`; then `make test && make lint`.

### Evidence index
- Commit reviewed: 891b5a543b50bb961cecfc228a2451de3a89462b; wave boundary 14a9d4a54c896116458b97b5301bd4e04fae33e0.
- Notes: full Terraform task including phase-1-review overrides; Spec decisions/acceptance/verification; PR context final Terraform handoff.
- Files: all 23 paths in Terraform commit, plus canonical DynamoStorage and Box delete adapter for interface review.

### Tests/Commands Run
- `make test && make lint` → PASS, 85 tests; lint and format pass.
- Credential-free `make test` as above → FAIL, missing profile.
- Credential-free `uv run --locked pytest -q` → PASS, 85 tests.
- `terraform fmt -check -recursive` → PASS.
- Isolated copy with local backend: `terraform init -input=false -lockfile=readonly`, `terraform validate`, `terraform plan -input=false -out=<temporary plan>` → PASS; 66 creates. Invoked via existing scripts.infra.terraform refreshable credential helper; AWS reads only. Temporary binary SHA verified against official release checksum.
- `git diff --check 14a9d4a..891b5a5` → PASS.
- Changed-file credential-pattern scan → no matches.
- Current Lambda archive size/hash → matches committed live proof.

### Risk Notes
- Acceptance is infrastructure/placeholder-only; cookie auth, actual sync/training/worker functionality are later-wave work.
- No deploy/destroy rerun; accepted earlier live proof per assignment. Final topology independently validated/planned.
- No base rebuild or pre-existing failure claim: failing global export is visibly introduced by Terraform commit.
- Fix request sent to implementor; no code changed. Task was already complete before verification; coordinator must reopen it if terminal-state protection refuses review_required.


## Verifier correction: credential-free Make targets

Fixed global AWS profile export in Makefile only; exports now apply only to cloud commands. Commit0b17dcd41055cbf18061672cfc32a369ebf99498. Exact credential-free make test repro PASS85, normal make test PASS85, make lint and git diff --check PASS. No cloud operations or resource changes; PR-context follow-up appended.

## Verifier findings — final recheck at 0b17dcd

### Verification Summary
- Verdict: ✅ APPROVED
- Confidence: High
- Exact head: 0b17dcd41055cbf18061672cfc32a369ebf99498. This supersedes the previous NOT APPROVED verdict at 891b5a5.
- No spec ambiguity. Infrastructure/placeholder task only.

### Acceptance Criteria Checklist
- ✅ VERIFIED — Terraform foundation, selected Region, resource scope and placeholder permissions: previously reviewed 891b5a5 Terraform files are unchanged in fix commit; independent init/validate/66-create read-only plan and formatting checks remain applicable.
- ✅ VERIFIED — Final secret topology: unchanged existing Box secret reference, separate auth/cookie secrets with out-of-band values, approved origin-state exception; independent final plan inspection previously passed.
- ✅ VERIFIED — Placeholder deploy/destroy Definition of Done: accepted live infra/evidence proof shows CloudFront static/health 200, direct API 403, zero owned resources after teardown and POC resources preserved. Final secret placement independently planned, not live reapplied, as authorized.
- ✅ VERIFIED — Package gate: unchanged 48,629,206-byte unpacked Linux Python 3.12 artifact/hash and accepted 1.473-second live cold import; no torch/transformers.
- ✅ VERIFIED — Scope/no secrets: fix changes Makefile only, target-scoping AWS_PROFILE/NAME_PREFIX exports; contains no secret values or cross-task source edits. Prior 23-path review remains applicable.
- ✅ VERIFIED — Credential-free make test: independently reran exact isolated-environment reproduction at fix head; all 85 tests now pass. Normal suite and lint also pass.

### Evidence index
- Commits: 891b5a543b50bb961cecfc228a2451de3a89462b and 0b17dcd41055cbf18061672cfc32a369ebf99498, scaffold boundary 14a9d4a54c896116458b97b5301bd4e04fae33e0.
- Notes: full Terraform task/overrides and correction handoff, Spec, PR context.
- Fix files: Makefile only. Infrastructure and artifact unchanged.

### Tests/Commands Run
- `env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true make test` → PASS, 85 tests.
- `make test && make lint` → PASS, 85 tests and lint/format.
- `git diff --check 14a9d4a..0b17dcd` → PASS.
- `make -n deploy` → expected build then deployment commands; no deployment executed.

### Risk Notes
- Live placeholder deployment/teardown proof accepted from implementor as assigned. Final secret correction independently validated/planned, not deployed again.
- Application integration/cookie auth/training/actual worker behavior remain later-wave scope.
- Verifier changed no repository files and created no live cloud resources.
