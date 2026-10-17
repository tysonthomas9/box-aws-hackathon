# Web app on AWS: API, shared-password login and four screens

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `fffe5129-b6ff-471d-b49d-d77af31fdc34`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

The demo surface.

## Scope
API Lambda (FastAPI via Mangum) behind API Gateway, reached through CloudFront /api/*. Static UI in plain HTML + JS (no build step) on S3. Login with the shared password → signed, expiring, HttpOnly cookie; origin/CSRF check on writes; basic throttling. Screens:
- **Sources:** Box files and versions, recent sync runs (trigger, timing), Sync now.
- **Review:** items with quote, flag reasons, old vs new; approve/edit/reject; review mode.
- **Ask:** one question → asynchronous jobs for without / with / search, polled; latency, model version, citations; Warm up button; Train now with Step Functions progress.
- **Results:** sealed hidden-set scores by question type for the three modes, the hash and the overlap check; version list with manifests.
Not in scope: Cognito, user accounts.

## Definition of Done
API tests against fakes; every screen works on the deployed stack; screenshots attached to this task note.

## Verification
`make test`; after `make deploy`, log in through CloudFront and click through every screen.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **This task owns asynchronous Ask:** dispatch, SQS worker code, job store, states (queued, warming, running, succeeded, failed), retries, expiry and polling. Each job **pins the model ARN and snapshot** when it is created, so a promotion can't change a queued comparison. Bounded timeouts (about 6 min including cold start).
- **Route-security matrix tests:** public login shell and `/api/login`; signature-only webhook; everything else needs the cookie (missing and expired cookie both rejected); CSRF/Origin on writes; direct API calls without the CloudFront origin header rejected. Cookie is Secure, HttpOnly and SameSite, signed with its own key.
- Show the serving version and a "stale" badge when approved items are newer than the serving model.
- DoD adds: a real comparison through CloudFront of the base vs a trained candidate ARN, including surviving a forced cold start.


## Extraction interface (from the extraction task, 2026-10-17)
Use `ExtractionService.reviews()`, `.decide()` and `.snapshot()`. Never infer effective items from raw proposals. The effective items, review decisions and processed batches live in one revision-checked knowledge record (fails closed above 350 KB); immutable content-addressed snapshots are separate records, and training takes its snapshot from `.snapshot()`.

## Implementation progress

Building credential-free API/UI with FastAPI + Mangum; atomic Ask job store, bounded worker and route-security tests. Own files: kloop/web/, lambdas/api.py, lambdas/ask_worker.py, web/, tests/test_web*.py, API dependencies. No AWS or Box resources will be created. Deployment screenshots and live cold comparison remain deploy-task integration checks.

## Readiness requirement update

Coordinator changed readiness to 15 minutes and sequential warm-up. Implemented a single ordered warm-up job (base first, then trained), immutable 900s deadline and owner-fenced lease blocking overlapping warm-ups. UI says warming (may take a few minutes). Tests exercise base taking >5 minutes then trained, exact call order, cross-worker lease refusal, and deadline expiry. Minimal Answerer configurable cap expansion preserves the default for existing callers.

## Browser proof — fake data only

Real API, secure-cookie login and plain UI exercised through a task-owned local HTTPS test proxy; AWS/Box/model adapters were fakes. Clicked review approval/mode, three-mode comparison, sequential Warm up, Train now, and logout. No page errors; Results accessibility audit: zero violations. This is not deployed CloudFront or real-model acceptance.

![login screen with fake data](workspace-asset://wandering-puffin/mvc2vzuf-00e0477b.png)

![sources screen with fake data](workspace-asset://wandering-puffin/mvc2vzwb-845d80e3.png)

![review screen with fake data](workspace-asset://wandering-puffin/mvc2vzy3-8f5910fe.png)

![ask screen with fake data](workspace-asset://wandering-puffin/mvc2vzzw-6bd14b6d.png)

![results screen with fake data](workspace-asset://wandering-puffin/mvc2w01r-18b87e20.png)

![warm-up screen with fake data](workspace-asset://wandering-puffin/mvc2w03r-c7f9fb1f.png)

## Final handoff

Implementation complete for task fffe5129-b6ff-471d-b49d-d77af31fdc34 under the coordinator's no-live-deploy scope.

Pushed branch withered-cobra, commits 0109129666ab392f4144a7d8fe199f39e0244a01, 38052974d4346caa7dd3c8a350ad60e3e7662a04, d1fb36b1390ed28f778d3df8ac533ca272344901. Implementation base afbd0b678ca9d368c64834435fc30e6b26f20502 (task started at fc54528b717ff395977181c76b2c53f42a9a1a8b). Final head d1fb36b1390ed28f778d3df8ac533ca272344901; tree 457dbdbca37c1c2e01d5b26c4c0f71e12d09cfe5. No PR created, per standing instruction; no PR URL/number.

Changed: kloop/web/{api,jobs,runtime,security,__init__}.py; lambdas/{api,ask_worker}.py; web/{index.html,app.js,style.css}; canonical PinnedModel/AskJob in kloop/schemas.py; bounded readiness and approved quote spans in kloop/answer/{__init__,bedrock}.py; tests/{test_web,test_answer,test_schemas}.py; pyproject.toml, uv.lock; six PNG screenshots under .intent/artifacts/web-proof/. Terraform unchanged.

Delivered signed expiring Secure/HttpOnly/SameSite shared-password cookie, CloudFront origin guard, Origin+CSRF checks, durable throttling, signature-only webhook bridge, Sources/Review/Ask/Results, persistent review modes, model version and stale badge, train dispatch/progress, immutable per-mode model/snapshot pins, CAS-owned jobs, SQS partial failures and expiry, 15-minute readiness. Warm up is one globally leased job loading base then trained sequentially. Search verifies exact pinned Box versions and limits retrieval to approved supporting quotes, preserving original citation offsets. Results excludes private sealed answers and explicitly distinguishes absent overlap results from a verified pass.

Gates at 2026-10-17 07:34 UTC: exact final head in isolated clean worktree, AWS credential/profile environment variables removed and metadata disabled: make test PASS (229), make lint PASS, node --check web/app.js PASS. Shared pending integration tree also passed normal and credential-free gates (latest 275 tests). Known warning: Starlette deprecates httpx TestClient; no failures. No known baseline failures; no base-SHA CI run exists for this task (no PR/CI link available). Real browser with real API through task-owned local HTTPS proxy and fake AWS/Box/model adapters: login/logout, review approval/mode, Ask polling, sequential warm-up, Train now clicked; no page errors, Results axe audit zero violations. Six screenshots attached as note assets; fake evidence only.

Deployment integration remains with task f8eca485-97ba-427c-87c0-16f0fad96372: handlers lambdas.api.handler and lambdas.ask_worker.handler, KLOOP_PUBLIC_ORIGIN, KLOOP_EXTRACTION_FACTORY=kloop.extract.runtime:factory, KLOOP_TRAINING_FACTORY=kloop.train.runtime:service, KLOOP_TRAINING_ARN, base ARN, tables/queue/secrets and scoped permissions documented there. Keep Ask Lambda timeout 900s; enable ask_jobs expires_at TTL; API/worker require GetItem/PutItem/DeleteItem for job+warm lease. KLOOP_REPORTS_TABLE defaults to versions table. Evaluator can provide optional overlap_audit; hash alone is not displayed as pass.

No live deployment or real-model calls; AWS/Box resources created: none; live spend $0. CloudFront screens, base-vs-trained comparison and forced cold start remain deployment acceptance work. Local HTTPS proxy stopped, owned named browser closed, isolated publication worktree and /tmp proxy files removed. Other agents' uncommitted files were not staged or changed.

## Verifier findings — web app task fffe5129 (2026-10-17)

### Verification Summary
- Verdict: ✅ APPROVED for the credential-free wave 3 scope.
- Confidence: High within that scope.
- No concrete implementation defects found. No spec ambiguity remains: the coordinator recorded “Acceptance deviation: wave 3 live proof” in the spec and confirmed it directly. CloudFront screens, real three-mode comparison and forced cold start remain deployment/demo e2e acceptance, not verified here.

### Acceptance Criteria Checklist
- ✅ VERIFIED — API tests against fakes.
  - Evidence: tests/test_web.py:167–473; injected Services in kloop/web/api.py:37; moto fixtures in tests/conftest.py.
  - Verification: credential-free make test: 280 passed.
- ✅ VERIFIED — signed expiring cookie, independent key, Secure/HttpOnly/SameSite, cookie requirements, Origin/CSRF on writes, origin guard, signature-only webhook and throttling.
  - Evidence: kloop/web/api.py:52–148; kloop/web/security.py:15–85.
  - Verification: route matrix missing/expired cookies, every write CSRF/Origin, tampering/direct origin, durable throttle, signature/tamper tests all passed.
- ✅ VERIFIED — Sources, Review, Ask and Results surfaces and attached screenshots.
  - Evidence: web/index.html:42–129; web/app.js:88–365; six committed screenshots in .intent/artifacts/web-proof/ and task-note asset links. Sources shows version/trigger/timing and Sync now; Review quote/reasons/previous/candidate/actions/mode; Ask polling/latency/version/citations/warm-up/train progress; Results counts/types/hash/audit/bindings/caveats/manifests.
  - Verification: API screen test passed; static UI/API contract review; independently opened all six existing fake-data screenshots. Existing browser click evidence is implementor evidence, not a new browser run by this verifier. Current explicit overlap status added after the Results screenshot is verified statically in web/app.js:336–350.
- ✅ VERIFIED — asynchronous per-mode jobs pin ARN/snapshot at creation; retries, expiry, polling and bounded cold starts.
  - Evidence: kloop/web/api.py:194–264; kloop/web/jobs.py:112–264; lambdas/ask_worker.py. Dynamo CAS, sequential globally leased warm-up and immutable 900s deadline.
  - Verification: memory/moto tests passed for immutable ARN, warming/success/redelivery, queue partial failure, expiry, concurrent claim refusal, crashed worker deadline and 600s sequential warm-up.
- ✅ VERIFIED — serving version and stale badge.
  - Evidence: kloop/web/api.py:183–192; web/app.js:176–189; kloop/web/runtime.py:75–95.
  - Verification: stale true/false API assertions passed; Ask screenshot reviewed.
- ✅ VERIFIED — use effective extraction service interfaces; no raw proposal inference.
  - Evidence: kloop/web/api.py:159–181, 198–199; kloop/web/runtime.py:136–155 uses immutable snapshot integrity and exact source-version verification; approved quote filtering in kloop/answer/__init__.py:52–115.
  - Verification: static cross-module interface review and passing extraction/answer/web tests.
- ✅ VERIFIED — live proof assigned to deployment under the accepted spec deviation.
  - Evidence: spec section “Acceptance deviation: wave 3 live proof (2026-10-17)”; coordinator confirmation. Live criteria are explicitly deferred, not represented as passed AWS/Box evidence.
  - Verification: read current spec; made no live AWS/Box/model calls.

### Evidence index
- Reviewed pushed branch withered-cobra at HEAD = origin/withered-cobra = 7e68a5b4232aa773b490321f4df7d7c9a1389287.
- Task commits: 0109129666ab392f4144a7d8fe199f39e0244a01, 38052974d4346caa7dd3c8a350ad60e3e7662a04, d1fb36b1390ed28f778d3df8ac533ca272344901. Task implementation base afbd0b678ca9d368c64834435fc30e6b26f20502.
- No subsequent changes to web/task-owned files between d1fb36b and reviewed HEAD. Reviewed newer training/evaluation interfaces for compatibility.
- Notes: spec, task fffe5129-b6ff-471d-b49d-d77af31fdc34, PR context 846fb942-136d-4b81-98f2-354a4926f1de. No PR/CI URL exists.

### Tests/Commands Run
- `env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI -u AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_EC2_METADATA_DISABLED=true make test` → PASS: 280 tests, one Starlette TestClient deprecation warning.
- `env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN AWS_EC2_METADATA_DISABLED=true make lint` → PASS: Ruff checks and 75 files formatted.
- `node --check web/app.js` → PASS.
- `git diff afbd0b678ca9d368c64834435fc30e6b26f20502 d1fb36b --check` → PASS.
- Relevant-path working-tree diff → clean; unrelated pre-existing POC evidence/rules left untouched.
- Changed-file scan for AWS access keys, private keys and GitHub tokens → zero matches; bounded scan, not an exhaustive history audit. No secrets printed.

### Risk Notes
- This is fake/moto/static evidence. No deployed routing, real-model readiness or forced cold-start acceptance is claimed.
- Six screenshots are prior implementor evidence and not a fresh visual test at reviewed HEAD.
- No product code changed and no resources created. No base rebuild was needed.

Re-verify credential-free with the exact commands above. Deployment owners must run the CloudFront login/four-screen walkthrough, real three-mode comparison and forced cold-start check under deploy task f8eca485-97ba-427c-87c0-16f0fad96372 and demo e2e task 5e5b5496.
