# Box sync service: webhook, schedule and Sync now

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `ee66bfb8-ad0c-4d0f-842f-de087a8e95cd`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Detect Box changes and feed extraction.

## Scope
Sync Lambda: triggered by the webhook route, EventBridge every minute, and Sync now. Webhook handler: verify the signature (Box client), dedupe on the body event id (DynamoDB TTL table), return 2xx within a few seconds, and enqueue work asynchronously. Sync: compare file version ids with the cursor table, skip unchanged files, extract new versions, retire items from deleted files; a per-folder lock so overlapping runs don't double-process. Record every sync run (trigger, files seen, changes, duration) for the Sources screen. Webhook create/delete is part of seed and destroy (cleanup ledger).
Not in scope: extraction internals, UI.

## Definition of Done
Tests: duplicate delivery is processed once; a bad signature is rejected; an unchanged file is skipped; a deleted file retires its items. Live: a Box edit appears as review items within 60 s via the webhook, and via the schedule with the webhook disabled.

## Verification
`make test`; live check after deploy.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Durable receipt → dispatch:** write the webhook receipt and enqueue in a way that can't lose work if the Lambda crashes after dedupe (e.g. write a pending record and have a reconciler re-dispatch stale pending records); mark a file version synced only after its items are durably stored.
- Handle **FILE.TRASHED** webhook events (subscription added in wave 2): dispatch them to sync, which retires the file's items.
- **Never infer deletion** from a failed or partial listing; paginate fully; exclude the `reports/` folder.
- Latency targets: webhook path, review items **≤60 s** (measured); schedule path, a separate measured bound (≤3 min).
- DoD adds: an unchanged re-sync produces no changes; a review rejection is honoured on the next sync.

Implementation started at d59d505. Owning kloop/sync/, lambdas/sync.py and tests/test_sync.py. Durable pending webhook receipts will remain recoverable until a worker completes. Extraction is injected through process(file_id, version_id) and retire(file_id), with persistence/review decisions owned by extraction. No live deployment or resources.

## Implementation and handoff — 2026-10-17T07:06:38Z
Task: ee66bfb8-ad0c-4d0f-842f-de087a8e95cd. Base read: d59d505; commit parent after the pack agent's commit: 2d92038. Committed and pushed d4b8df35f5b428bfd27154caeaaec36b977f0ece on withered-cobra; git pull --rebase was up to date. No PR requested or created.

Implemented durable signature-checked webhook ingress (body event-id dedupe, asynchronous Lambda dispatch), scheduled/manual sync, a per-folder conditional DynamoDB lease, complete recursive listing excluding reports/, version skipping, deletion/FILE.TRASHED handling through retirement, and per-run history (trigger, event id, files seen, changes, duration, status, safe error type). Receipt rows have no TTL until successful worker completion; the 1-minute scheduled worker recovers undispatched/failed receipts. Receipts arriving during a scan remain pending. Cursors advance only after extraction returns durable success. Seed with --webhook-url now reserves a cleanup row before creating, verifies, and resolves as the final step; destroy already deletes ledger-owned hooks.

Extraction task 631555a7 must implement kloop.sync.service.Extraction: process(file_id, version_id) -> int and retire(file_id) -> int. Both methods must be idempotent across partial writes and preserve rejected review decisions. retire proposes retirement for review, rather than deleting approved items. Unchanged versions do not call extraction. No extraction internals are implemented in sync.

Runtime integration: lambdas.sync.compose(session, extraction), lambdas.sync.handler for trusted worker events {source: schedule|manual|webhook, event_id?: string}. API route uses lambdas.sync.ingress_runtime().webhook(request) for the signature-only /api/box-webhook, and .sync_now() after cookie/CSRF checks. Ingress does not construct extraction or CCG. Worker runtime loads KLOOP_EXTRACTION_FACTORY=module:function; factory(session) returns the real extractor, with no fake fallback.

Deploy wave must set the sync handler to lambdas.sync.handler, configure KLOOP_BOX_FOLDER_ID, KLOOP_SYNC_FUNCTION_NAME, KLOOP_EXTRACTION_FACTORY, existing KLOOP_SYNC_CURSORS_TABLE and KLOOP_WEBHOOK_DEDUPE_TABLE, and grant required table/secret/InvokeFunction permissions. Sync run history is collection sync_runs and cursors are sync_cursors:<folder_id> in the sync-cursors table. Lease is 960 seconds (longer than Lambda's maximum 900-second lifetime); it must remain longer than the worker hard runtime. API ingress needs receipt writes, cursor-table access for composition, signing-secret reads, and async invocation. Seed webhook requires KLOOP_CLEANUP_LEDGER_TABLE, NAME_PREFIX and --webhook-url / KLOOP_BOX_WEBHOOK_URL. Runtime auth is existing CCG service account; existing Box secret fields webhook_primary_key and webhook_secondary_key fail closed when absent.

Verification at 2026-10-17T07:06:38Z: make test PASS (126 tests including 25 sync tests); make lint PASS (ruff check and format); git diff --check PASS. Covered duplicate event/different delivery ids, invalid and absent signatures, signed base64, FILE.TRASHED/FILE.DELETED, unchanged/rejected-review preservation, failed extraction and retirement retry checkpoints, crash-before-dispatch recovery, no pending TTL, overlapping/expired leases, full pagination and failed partial listing, reports exclusion, receipt arrival during scan, async/manual/schedule handlers, fail-closed extraction factory, and ledger reserve/create/verify/resolve order with uncertain-create retention.

Files: kloop/box/cli.py; kloop/sync/__init__.py; kloop/sync/ingress.py; kloop/sync/service.py; kloop/sync/state.py; kloop/sync/subscription.py; lambdas/sync.py; tests/test_sync.py.

No live AWS/Box resources created or mutated. Live signing-key delivery and measured <=60s webhook / <=3min schedule targets are explicitly deferred to deploy as assigned. Full real-extraction rejection/retry semantics must also be verified by extraction/integration tasks. No pre-existing test failures observed; base CI was not inspected and no base CI failure link is claimed. Other agents' pack and model-experiment files and untracked AGENTS.md/CLAUDE.md were not staged.


## Approved interface follow-up — 2026-10-17T07:08Z
Task ee66bfb8-ad0c-4d0f-842f-de087a8e95cd; PR none. Coordinator's queued approval requested the Protocol in a shared location with a reusable fake. Moved Extraction to kloop/sync/ports.py and added FakeExtraction in kloop/sync/testing.py; service and worker import the shared Protocol. Added a crash-after-extraction/before-cursor test demonstrating idempotent replay with the fake. Base d4b8df35f5b428bfd27154caeaaec36b977f0ece; head 142e8ae0a78e1bdf6bad5b2cc8735ebd33698f4b. make test PASS (127 tests, 26 sync); make lint PASS; git diff --check PASS. No known base CI failures observed; base CI not queried (no link claimed). Files: kloop/sync/ports.py, kloop/sync/testing.py, kloop/sync/service.py, lambdas/sync.py, tests/test_sync.py. Live proof remains deferred as previously assigned. Task remains complete.

## Verifier result — 2026-10-17
❌ NOT APPROVED (High confidence). Normal full gates pass 127 tests; full credential-free run fails with 1 failure and 19 errors (ProfileNotFound: box-hackathon). Sync-only credential-free tests pass all 26. Isolated repro: run pending-cleanup infra test then test_expired_lock_is_recoverable; infra main leaks AWS_PROFILE into the next test. Coordinator must reopen this already-complete task and authorize or assign the narrow environment-isolation repair. Full evidence, criterion checklist and exact rerun commands appended under Verifier findings — Box sync in PR context 846fb942-136d-4b81-98f2-354a4926f1de. No source changes or live resource operations. Latency proof remains accepted deploy-wave work.

## Credential-free gate repair — 2026-10-17T07:12:24Z
Task ee66bfb8-ad0c-4d0f-842f-de087a8e95cd; PR none. Coordinator reopened/authorized the narrow infrastructure-test isolation fix. Base 02d0857b61a758b4586dc2c3958294107fa5f66b; head b382cd574575dcb4672dafa85063b61460f081e2.

Reproduced the verifier failure: with AWS_*, BOX_* and KLOOP_BOX_* removed, AWS_CONFIG_FILE=/dev/null, AWS_SHARED_CREDENTIALS_FILE=/dev/null, AWS_EC2_METADATA_DISABLED=true, BOTO_CONFIG=/dev/null, the full suite failed after the infrastructure destroy test leaked AWS_PROFILE=box-hackathon. A module-local autouse fixture now registers AWS_PROFILE, AWS_DEFAULT_REGION, TF_VAR_aws_profile and TF_VAR_name_prefix with monkeypatch, restoring their prior presence/value after each infrastructure test. scripts/infra.py behavior is unchanged. Worker runtime now checks KLOOP_EXTRACTION_FACTORY before constructing an AWS Session; its existing failure test explicitly uses an unavailable profile and empty config files.

Verification at 2026-10-17T07:12:24Z: credential-free make test PASS (127), credential-free make lint PASS; normal make test PASS (127), normal make lint PASS; git diff --check PASS. The test process received a filtered child environment; no host configuration or credentials changed. Files: tests/test_infra_commands.py, tests/test_sync.py, lambdas/sync.py. No live resources. Pre-existing base local failure reproduced as above; base CI not inspected/no CI failure link claimed. Extraction/deploy live-proof deferrals unchanged. Verifier agent-c03b9ccd-1ad5-49bf-97f2-4ed495b63c4c to re-check the fix.

## Verifier result — repair approved, 2026-10-17
✅ APPROVED, High confidence for code/offline task scope. Repair b382cd5 independently tested at shared head fc54528; normal and exact credential-free make test && make lint PASS (127 tests each), prior two-test failure PASS (2). Full repair diff reviewed; coordinator-authorized module-local environment isolation and factory-before-Session validation resolve the only blocking finding. All other sync criteria remain verified; accepted live/deploy/extraction integration deferrals unchanged. No source edits or live resources by verifier. Full updated checklist and rerun commands are in PR context under Verifier findings — Box sync repair approved. This supersedes the previous NOT APPROVED verdict.
