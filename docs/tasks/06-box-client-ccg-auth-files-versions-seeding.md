# Box client: auth, files, versions, webhooks, seeding

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `e9fa2502-748b-4049-ae95-ec481bcf4b49`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

A small Box module the rest of the system uses.

## Scope
`kloop/box/` on the official Python SDK (box-sdk-gen). Follow the vendored Box skills (`.claude/skills/box*`) and the [POC 3 runbook](../pocs/poc-3-runbook.md). Token provider interface: CCG (default, from `box-hackathon/box-ccg`, subject type user/enterprise from the secret), developer token (testing), OAuth refresh token (fallback, refresh token rotated back into Secrets Manager). Operations: list folder, get file + current version, download text, upload/new version, delete (only inside the configured Halvard folder), create/delete webhook, verify webhook signatures (primary/secondary keys, raw body + timestamp, timing-safe compare, 10-minute replay window). Rate-limit retries with backoff. `make seed` helper: create the Halvard folder and upload the knowledge pack.
Not in scope: extraction, sync logic.

## Definition of Done
Unit tests with a fake Box and recorded fixtures, including signature-verification vectors; a live smoke script (`make box-smoke`) that runs with real credentials when present.

## Verification
`make test`; `make box-smoke` with a developer token or CCG.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Build one production auth path, not both:** CCG (pending Tyson's admin authorization) plus the developer token for testing. The OAuth app is a separate Box app and consent flow: only build it if Tyson confirms CCG can't be authorized, and then serialize refresh-token rotation across Lambdas (refresh tokens are single-use).
- Webhook signatures: HMAC-SHA256 over raw body + timestamp bytes, Base64, either key matches, constant-time compare, freshness check. Events are **rejected** until keys exist (no unsigned acceptance in the deployed system).
- Live smoke covers list/download/extract/upload/webhook under the deployed actor.


## Implementation started
Base 14a9d4a54c896116458b97b5301bd4e04fae33e0. Scope confirmed: official box-sdk-gen 1.17, CCG plus explicit developer-token testing, no OAuth. Own kloop/box/, tests/test_box.py and fixtures; minimal coordinated pyproject.toml/uv.lock/Makefile additions. Live smoke will use a new owned folder only, clean its own uploads/webhook, and report missing signing keys separately. No extraction/sync business logic.


## Delivered — 2026-10-17 06:34 UTC
Commit `0468f131b249e1e52e5fdb760843e47655f7efa8` pushed to `withered-cobra`. Task base `14a9d4a54c896116458b97b5301bd4e04fae33e0`; immediate parent includes the parallel answer task (`8eb7660`). No PR exists yet.

- Official `box-sdk-gen` adapter in `kloop/box/`, implementing `kloop.ports.BoxClient` with canonical `Document`; marker pagination, current metadata, pinned-version UTF-8 downloads (5 MiB limit, closed on failure), uploads/new versions, ETag-guarded deletes, folder-boundary enforcement and scoped webhook registration/deletion.
- `CCGTokenProvider` consumes `client_id`, `client_secret`, `box_subject_type` (`user` or `enterprise`), `box_subject_id`. SDK caches/renews access tokens in memory. `DeveloperTokenProvider` is explicit testing only; never a silent actor fallback. No OAuth implementation. Runtime Secrets Manager read is injected, using `KLOOP_BOX_SECRET_ID` (default `box-hackathon/box-ccg`).
- Webhook verifier accepts raw bytes + headers + primary/secondary key strings; HMAC-SHA256(body bytes then original timestamp bytes), Base64, constant-time comparison, case-insensitive headers, 10-minute window, future/naive/malformed timestamp rejection. No configured keys means rejection. Sync owns event-id dedupe and loading its signing-key secret.
- `seed(client, pack_path, storage=...)` uses the frozen POC2 pack (10 facts, 3 procedures), verifies uploaded content, retains file/version IDs and hashes using the existing Storage contract when supplied, skips unchanged files, and versions changed files. No hidden questions/data builders included.
- Commands in `kloop/box/commands.mk`: `make seed` and `make box-smoke`, CCG by default; use `BOX_AUTH=developer` for testing. Set `KLOOP_BOX_FOLDER_ID` for the existing Halvard folder. With no folder configured, seed creates Halvard Systems and prints its id; retain that id in configuration. Seed manifest is printed; callers can inject Storage to persist it. Optional `KLOOP_BOX_WEBHOOK_URL` enables the smoke registration/read/delete check.

### Verification
At 06:34 UTC: `make test` PASS (82 current checkout tests, including 37 Box tests); `make lint` PASS; `git diff --check` PASS. Tests include sanitized POC3 metadata fixtures, fixed signature vector, rotation/freshness/body-tamper cases, folder limits, streams closed after interruption, actual SDK retry transport with Retry-After and bounded attempts, CCG wire fields/token reuse/renewal, and stable/changed seeding with MemoryStorage. No base CI runs returned by `gh run list --commit 14a9d4a...`; no known pre-existing failing gates.

Live `make box-smoke BOX_AUTH=developer` PASS for upload/download/list/old versions and pinned-model Box AI extraction transport. Owned temporary folder `428393066033` and its uploaded file/versions were deleted; folder GET returned 404. No AWS resources created or modified; project plan verified FREE/ACTIVE and configured Region us-east-2. No secret values printed or persisted.

### Explicit limits and shared-file handoff
CCG remains admin-unauthorized per coordinator; this run did not retry it. Signed delivery is NOT proven because no deployed receiver or signing keys were available. Webhook registration live step was explicitly skipped without a receiver URL; SDK/fake coverage exists. Smoke extraction is a transport check, not extraction-quality acceptance. `make seed` was verified offline through the fake and Storage, not run against the permanent Halvard folder.

Shared dependency change: `boto3[crt]` added at answer agent request for AWS social login. Shared Makefile contains only my appended `include kloop/box/commands.mk` plus other agents’ targets; infra agent was asked to commit the shared Makefile, so it was intentionally omitted from my scoped commit. Other uncommitted infra files and untracked AGENTS.md/CLAUDE.md were left alone. `git pull --rebase` was refused because shared infra edits were unstaged; fetched instead, verified remote was an ancestor (0 remote-only, 1 local-only), then pushed successfully without stashing another agent’s work.

Files committed: pyproject.toml, uv.lock, kloop/box/{__init__.py,auth.py,client.py,webhooks.py,seed.py,cli.py,commands.mk}, tests/test_box.py, tests/fixtures/box/{file.json,webhook.json}.



Exact committed-head check at 06:35 UTC: archived `0468f131b249e1e52e5fdb760843e47655f7efa8` into an owned `/tmp` directory, ran locked pytest (75 PASS) plus ruff check/format (PASS), then removed only that temporary directory. This excludes other agents’ uncommitted infra tests and shared Makefile edits.



## CCG authorization retry and signing-key contract — 2026-10-17T06:37Z
Task e9fa2502-748b-4049-ae95-ec481bcf4b49. Coordinator reported CCG authorization enabled for app 2709846 and requested one live CCG smoke. At 2026-10-17T06:36:49.916297Z, read box-hackathon/box-ccg in us-east-2 and used CCGTokenProvider with secret subject type user and secret subject id. Token request failed HTTP 400, exact credential-redacted response body:
```json
{"error":"invalid_grant","error_description":"Grant credentials are invalid"}
```
No token issued, so users/me, folder CRUD and extraction under CCG were NOT RUN. No Box resources created, no cleanup required. Previous developer-token smoke remains the only successful live actor proof. No retry after this failure; coordinator notified to check authorized-app/client credentials/subject match. Both webhook_primary_key and webhook_secondary_key were absent in the secret at this timestamp; no signed-delivery proof.

Added/exported webhook_keys(secrets_client, settings), reading those exact fields from KLOOP_BOX_SECRET_ID (default box-hackathon/box-ccg), returning primary_key/secondary_key kwargs for verify_webhook. Missing keys yield empty values and reject signatures. No secret values logged or persisted. Commit 99a0bc1e31da4dc8030548350c89d35ab1052619 pushed to withered-cobra; key-loader change based on Box head 0468f131b249e1e52e5fdb760843e47655f7efa8 (parallel shared commits may be in ancestry). PR none.

Gates at 06:37 UTC: 38 Box tests PASS; make test PASS (83 tests in shared checkout), make lint PASS, git diff --check PASS. Files: kloop/box/auth.py, kloop/box/__init__.py, tests/test_box.py. Known base CI failures: none known; no base CI run link available. Pull --rebase again refused shared unstaged infra edits; fetched, verified no remote-only commits, pushed without stashing shared work.



## Approved Box actor and folder ownership — 2026-10-17
Tyson approved enterprise-subject CCG for the app service account. The existing secret now uses box_subject_type=enterprise and box_subject_id=1559641916. Production seeding must use this CCG actor: the service account owns the Halvard Systems folder that `make seed` creates in its own root. Retain the returned folder id in KLOOP_BOX_FOLDER_ID; use the same service-account actor for source sync, extraction and webhook setup. A developer-token-created folder belongs to that developer actor and must not silently substitute for the service-account folder. Sharing the service-account folder to a human requires a separate authorized collaboration step, not an identity fallback. Webhook keys remain absent, so signed events must still fail closed.



## Enterprise CCG service-account proof — 2026-10-17T06:47Z
Task e9fa2502-748b-4049-ae95-ec481bcf4b49. Code head remains 99a0bc1e31da4dc8030548350c89d35ab1052619; no code/config/secret edits in this follow-up. Coordinator approved enterprise CCG subject 1559641916. At 2026-10-17T06:45:45.389064Z the CCGTokenProvider obtained an access token; users/me returned actor id 53095120751, name The Rubber Ducks, and a Box developer service-account login. Secret signing keys webhook_primary_key/webhook_secondary_key were both absent. Previous user-subject invalid_grant evidence is historical, superseded for the approved enterprise auth path.

### Owned live checks and cleanup
A bounded CCG diagnostic completed upload, exact pinned-version download, list_documents, one pinned aws__claude_4_5_haiku Box AI extract_structured call, delete_file and folder deletion. Folder 428393524290; file 2532349773310; version 2810056816510. Download bytes matched the uploaded smoke string. Box AI returned its typed response successfully; the optional local quality assertion hit TypeError (AiExtractResponse is not JSON serializable), so extraction transport is proven but answer content/quality is not scored here. Finally block deleted the file and folder and verified folder GET 404. No resources retained and no AWS resources created. No credentials/content printed or persisted.

### Retained diagnostic limitations
The first invocation reused the broader smoke helper, which additionally tries a new file version with If-Match. That extra version update returned HTTP 412; exact response body:
```json
{"type":"error","code":"precondition_failed","status":412,"message":"The resource has been modified. Please retrieve the resource again and retry","help_url":"https://developer.box.com/guides/api-calls/permissions-and-errors/common-errors/","request_id":"0286f90453bb2167c8e242f77935e4980"}
```
Its cleanup completed; subsequent service-account root listing had no kloop-smoke-* folders and no pagination remainder. The focused diagnostic above omitted this extra version-update step and finished only the requested CRUD/extract proof. Thus the full make box-smoke CCG command is NOT claimed green: the extra immediate version-update check saw 412, while the requested CCG actor/file/extraction transport operations worked. No second Box AI call was made after the local serialization assertion.

### Folder ownership for deployment
The **service account owns Halvard Systems**, which `make seed` creates in that actor’s root when KLOOP_BOX_FOLDER_ID is unset. Record its returned id in KLOOP_BOX_FOLDER_ID and use this same enterprise CCG actor for seed/sync/extraction/webhooks. No permanent Halvard folder was seeded in this smoke. Developer-owned folders are separate; no silent actor fallback or collaboration changes. Keys must still be added out of band to the existing secret, and unsigned events continue to fail closed. Signed webhook delivery remains untested.


## Verifier findings — Box client wave 2, 2026-10-17

### Verification Summary
- Verdict: ❌ NOT APPROVED.
- Confidence: Medium overall; high for offline gates and serialization diagnosis. Live writes were prohibited for this verification.
- Reviewed/tested shared head: 891b5a543b50bb961cecfc228a2451de3a89462b; scaffold base: 14a9d4a54c896116458b97b5301bd4e04fae33e0.
- Box changes: 0468f131b249e1e52e5fdb760843e47655f7efa8 and 99a0bc1e31da4dc8030548350c89d35ab1052619. No code edits, deployments, or live AWS/Box calls made.
- The unresolved full CCG smoke is a required verification gap before wave 3, not evidence that CCG authentication is broken. No ambiguous requirement prevents a verdict.

### Acceptance Criteria Checklist
- ✅ VERIFIED: Official SDK, CCG default plus explicit developer testing, no OAuth implementation.
  - Evidence: kloop/box/auth.py, client.py, pyproject.toml; enterprise-service-account success recorded in task note at 06:47Z.
  - Verification: static review; tests cover subject selection, token caching/renewal, explicit developer mode, invalid secrets. Live identity proof is prior implementor evidence, not independently rerun.
- ✅ VERIFIED: Folder listing, current file/version metadata, pinned downloads, scoped file/webhook operations and rate-limit backoff.
  - Evidence: client.py; sanitized fixtures; tests/test_box.py.
  - Verification: 38 Box tests passed within 85 total. Pagination, boundaries, stream closure, ETag forwarding, SDK transport Retry-After and bounded attempts covered. Live version-update qualification is separately unverified below.
- ✅ VERIFIED: Raw-body/timestamp HMAC-SHA256, Base64, either signing key, constant-time comparison, freshness and fail-closed missing keys.
  - Evidence: webhooks.py, auth.py:webhook_keys; fixed vector, rotation, tampering and freshness tests.
  - Verification: offline tests passed; checked against https://developer.box.com/guides/webhooks/v2/signatures-v2/. This does not prove live signed delivery.
- ✅ VERIFIED: Halvard seeding helper, frozen knowledge pack, stable repeats and changed-source versioning.
  - Evidence: seed.py, cli.py, commands.mk; fake/MemoryStorage tests persist IDs and hashes.
  - Verification: offline seed tests passed. Permanent service-account-folder seeding was not run and belongs to deployment proof.
- ✅ VERIFIED: Definition of Done unit tests/recorded fixtures and repository gates.
  - Evidence: tests/test_box.py and tests/fixtures/box/{file,webhook}.json.
  - Verification: make test && make lint PASS: 85 tests, ruff check, 28 files format-checked. git diff --check 14a9d4a..HEAD PASS.
- ⚠️ DEVIATION: “Live smoke covers list/download/extract/upload/webhook under the deployed actor.”
  - What differs: full CCG smoke at 06:45Z stopped at cli.py:50 → client.py:140 upload_version with HTTP 412 precondition_failed (request 0286f90453bb2167c8e242f77935e4980). Subsequent diagnostic omitted version upload; webhook registration was skipped; signed delivery lacks keys/receiver.
  - Impact: version updates are an explicit client operation and changed-source seeding uses this path. CRUD/AI transport success does not establish full smoke success. The 412 must be resolved or explained with successful required-path evidence before wave 3 approval; do not simply remove the version check.
  - Minimal fix: inspect fresh file ETag/version and outgoing If-Match around the failed update, distinguish a genuine concurrent change from header/API misuse, then fix only a demonstrated defect. Preserve conflict protection; blindly retrying/omitting If-Match could overwrite another actor. Add a regression covering the discovered cause.
  - Evidence limit: current code fetches metadata immediately before uploading and forwards current.etag; Box documents 412 as the expected response when ETag changed (https://developer.box.com/reference/post-files-id-content/). Existing evidence does NOT establish stale-header formatting, consistency delay, or a race as the root cause.
  - Re-verify: make test && make lint; then, in a separately authorized write-capable verification round, make box-smoke BOX_AUTH=ccg (including new-version creation, preserved old content and cleanup). With deployed receiver available: KLOOP_BOX_WEBHOOK_URL=https://<receiver>/api/box-webhook make box-smoke BOX_AUTH=ccg. Signed event acceptance/rejection needs receiver-level proof when keys exist.
  - Accepted boundary: coordinator explicitly allowed absent signing keys “for now” in the 06:45Z handoff. Offline verifier correctness is proven; live signed delivery remains a later integration dependency, not a newly discovered signature bug.
- ✅ VERIFIED: No cross-task edits beyond declared shared files; no committed secrets found in this task's changes.
  - Evidence: both Box commits touch only kloop/box/, tests/test_box.py, Box fixtures and coordinated pyproject.toml/uv.lock; commands.mk include appears in infra-owned shared Makefile.
  - Verification: commit/path inspection, manual auth/fixture review and credential-pattern scan of all 12 committed paths. Only scan hit is deliberately invalid test URL [invalid URL credential fixture omitted] (tests/test_box.py:189). No credential values found. This is bounded to this task's changes, not all history. Existing untracked AGENTS.md, CLAUDE.md and POC evaluation-status JSON were untouched.

### Precise serialization finding
- Real diagnostic bug, NOT a reproduced bug in committed Box client/smoke: the one-off CCG comparison ran json.dumps(result.answer). In SDK 1.17, answer is AiExtractResponse, so this raises TypeError.
- Independently reproduced offline using actual AiExtractStructuredResponse.from_dict(...); json.dumps(response.answer) raises the exact “Object of type AiExtractResponse is not JSON serializable”.
- response.answer.to_dict() serializes correctly. A fake-backed execution of the unchanged committed smoke using that actual SDK response type completes and its result serializes successfully. cli.py:77 only checks answer truthiness and emits primitive status fields.
- Required action: repair the diagnostic comparison before using it to claim answer correctness. This alone does not require a production Box-client fix or block wave 3 extraction work; extraction quality is outside this client task. Do not carry json.dumps(answer) into the extraction implementation.
- The smoke changes owner to test-only before extraction; any future content assertion must check the revised content rather than the original owner.

### Evidence index
- Commits reviewed: 0468f131b249e1e52e5fdb760843e47655f7efa8; 99a0bc1e31da4dc8030548350c89d35ab1052619; shared-head Makefile include in 891b5a5.
- Notes: spec; full Box task e9fa2502-748b-4049-ae95-ec481bcf4b49 including overriding phase-1-review amendments; PR context 846fb942-136d-4b81-98f2-354a4926f1de; implementor conversation service-account smoke.
- Areas: all Box package files, tests and fixtures, shared dependencies/Makefile; installed SDK upload and AI response interfaces.

### Tests/Commands Run
- make test && make lint → PASS (85 tests; ruff check and format).
- git diff --check 14a9d4a..HEAD → PASS.
- git show --stat 0468f13; git show --stat 99a0bc1; git log 14a9d4a..HEAD -- kloop/box tests/test_box.py → scope confirmed.
- Read-only credential-pattern scanner over 12 changed committed paths → only intentionally invalid URL fixture; no secrets found.
- uv run --locked python with actual AiExtractStructuredResponse and fake-backed smoke → direct answer serialization TypeError reproduced; answer.to_dict() PASS; committed smoke/result JSON PASS.
- make box-smoke / make seed → NOT RUN: creates/updates/deletes Box content, prohibited by this read-only assignment.
- git status --short → same three pre-existing untracked files; no tracked changes made.

### Exact re-verify commands
```sh
git rev-parse HEAD
make test && make lint
git diff --check 14a9d4a54c896116458b97b5301bd4e04fae33e0..HEAD
git status --short
```
Only after authorization for live temporary Box writes:
```sh
make box-smoke BOX_AUTH=ccg
KLOOP_BOX_WEBHOOK_URL=https://<deployed-receiver>/api/box-webhook make box-smoke BOX_AUTH=ccg
```

### Risk Notes
The earlier developer-token smoke passed, but does not substitute for the failing full smoke under the approved production CCG actor. No new cloud evidence is claimed. Required new-version proof remains unresolved; signed receiver proof is explicitly deferred until keys/receiver exist.


## Verifier findings — final recheck at d59d505
✅ APPROVED, High confidence within wave-2 scope. Supersedes the earlier NOT APPROVED gap. Full six-item verification is recorded in PR context 846fb942-136d-4b81-98f2-354a4926f1de and fixes task e87b3b00-cc85-4150-9241-770c201e44d0. Independently reran make test && make lint normally and with AWS/Box credentials removed: both PASS, 96 tests and lint/format. Accepted two full successful service-account CCG smoke runs as instructed, including version uploads, pinned old/new downloads, SDK to_dict comparison and GET-404 cleanup. Coordinator confirmed live signed delivery/trash-to-sync dispatch remain the sync task boundary. No source/cloud changes by verifier. Re-verify: make test && make lint; credential-free environment command in PR context; git diff --check d59d505^ d59d505.
