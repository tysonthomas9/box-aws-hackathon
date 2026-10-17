# Deploy, seed and demo runbook

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `f8eca485-97ba-427c-87c0-16f0fad96372`. Task status: **not started**. Earlier progress entries are historical; later dated entries record updates.

One command to stand up the demo, and a script to present it.

## Scope
`make deploy && make seed` end to end: upload the pack to Box, create the webhook, extract and auto-approve, train version 1 and a pre-trained version 2 (after the v2 edit), run the hidden set. `make smoke` checks every route. Demo runbook (note + `docs/demo.md`): the warm-up step, the live Box edit → webhook → review flow, the switch to pre-trained v2 (disclosed), the Ask comparisons per scenario, the Results screen, and fallbacks (cold start, webhook delay). `make destroy` verified clean (no imports, webhook or tagged resources left).
Not in scope: new features.

## Definition of Done
A fresh deploy + seed + smoke passes; the runbook was rehearsed once end to end with timings recorded; destroy leaves nothing behind.

## Verification
`make deploy && make seed && make smoke`; rehearse; `make destroy`.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Unattended proof:** after deploy, disconnect the laptop client and show sync → Train now → Ask completing on AWS alone (timestamps from CloudWatch).
- The pre-trained v2 must correspond to the exact reviewed v2 snapshot hash; the runbook says it is a playback of an earlier training run.
- Destroy verification covers partial failures and leaves pre-existing POC resources untouched.


## Integration wiring owed by this task (from wave 3)
- **Sync Lambda:** handler `lambdas.sync`; set the function name, `KLOOP_EXTRACTION_FACTORY=module:function` (supplied by the extraction task; sync fails closed without it), and the Halvard folder id. IAM: the sync/receipt/cursor DynamoDB tables, read on the `box-hackathon/box-ccg` secret, and lambda:InvokeFunction for async dispatch.
- **Seed:** registers the webhook URL through the cleanup ledger (`kloop/box/cli.py`); destroy already removes ledger-owned webhooks.


## Tyson must be able to edit in Box during the demo
The Halvard folder is owned by the CCG service account, so seed must also **add Tyson's Box user (id 53094349916) as an Editor collaborator** on the Halvard folder (recorded in the cleanup ledger, removed on destroy). That lets him make the live edit from his own Box web UI. Verify that he can see the folder.


- **Extraction wiring:** `KLOOP_EXTRACTION_FACTORY=kloop.extract.runtime:factory`; env `KLOOP_ITEMS_TABLE` (or `KLOOP_TABLE_NAME`), `KLOOP_BOX_FOLDER_ID`, `KLOOP_REVIEW_MODE=exceptions`; CCG secret read access.

## Web/API wiring contract (in progress)

API handler: lambdas.api.handler; SQS worker: lambdas.ask_worker.handler (ReportBatchItemFailures; batch_size=1 already defined). Upload web/index.html, web/app.js, web/style.css. Required API env: KLOOP_PUBLIC_ORIGIN=https://<CloudFront domain> (no trailing slash), KLOOP_EXTRACTION_FACTORY=kloop.extract.runtime:factory, KLOOP_TRAINING_FACTORY=kloop.train.runtime:service, KLOOP_BASE_MODEL_ID=<base imported model ARN>, optional KLOOP_BASE_VERSION_ID. Existing table/queue/secret names apply. Secrets auth/cookie-signing/origin contain raw strings; cookie key and origin key >=32 chars and distinct. API needs versions + items + sync cursors Dynamo reads, items review writes, ask_jobs puts, webhook_dedupe UpdateItem for durable throttles, sqs SendMessage, lambda InvokeFunction sync, states StartExecution training (training store lock writes). Ask worker needs ask_jobs GetItem/PutItem, items GetItem for approved snapshots, bedrock InvokeModel on deployment imports, and Box CCG GetSecretValue for exact approved-version document retrieval in search. Enable expires_at TTL on ask_jobs (1-day result retention after immutable 6-minute deadline); throttles use existing webhook_dedupe TTL. Worker invocation should be bounded to 360s. No Terraform changes made by web task. Live CloudFront/screenshots/forced-cold comparison remain your integration proof.


- **Web/API wiring:** handlers `lambdas.api.handler` and `lambdas.ask_worker.handler` (SQS); env `KLOOP_PUBLIC_ORIGIN`, `KLOOP_TRAINING_FACTORY` plus the existing table/queue/extraction settings; scoped runtime permissions (see the web task's handoff).
- **Warm-up:** 15-minute readiness bound; warm the base then the trained model sequentially before the demo.


- **Webhook signing keys are now present** in `box-hackathon/box-ccg` (`webhook_primary_key`, `webhook_secondary_key`, stored by Tyson at 07:27 UTC). The deploy wave must prove live signed delivery end to end (Box edit → signed webhook → review within 60 s).

## Web readiness correction — coordinator requirement

Supersedes the earlier six-minute/360s note: Ask and Warm up now have immutable 900s (15-minute) deadlines. Keep Ask Lambda timeout=900 (existing placeholder already correct). A single warm-up delivery pins base then trained and loads them sequentially; a DynamoDB owner-fenced warm-up lease prevents overlapping warm-ups. Ask role/API need DeleteItem on ask_jobs as well as GetItem/PutItem for releasing this lease. Answerer default retry budget stays 240s for other callers; web worker uses remaining deadline minus 65s transport reserve, capped at 840s. Still no Terraform edits by web task.

## Final API integration notes

Training factory confirmed: KLOOP_TRAINING_FACTORY=kloop.train.runtime:service, plus KLOOP_TRAINING_ARN (constructed ARN to avoid Terraform dependency cycle). Evaluation summaries: KLOOP_REPORTS_TABLE defaults to KLOOP_VERSIONS_TABLE, collection eval_reports. API exposes paired and optional overlap_audit summary; UI explicitly says result not reported if producer supplies only audit_sha256. Search verifies pinned source text and retrieves only approved Item.supporting_quote spans, retaining original source offsets; rejected text elsewhere in the same file is excluded. No live resources or spending from web task.

## Phase 1b change (2026-10-17)
The demo source is now Tyson's Box folder "The Rubber Ducks" (id 428390666255), not the seeded Halvard folder. Do not seed or create a Halvard folder. Skip the 'Tyson as Editor on Halvard' step: Tyson and the service account are already Editors. The Terraform state bucket from wave 2 was destroyed, so recreate the backend before apply. Deploy after Phase 1b tasks 1b-1..1b-3.

## Phase 1b additions (07:44 UTC)
- Webhook target folder: company-specific 428391006380 (permission proven by 1b-1).
- Box reports/ folder: create it inside The Rubber Ducks root only if needed; it is someone else's folder, so keep uploads minimal and named clearly.
- The live document-change scenario edits a COPY of the chosen document inside the folder, never the original, and restores it after rehearsal.
- Build the OpenUI web bundle inside make deploy (task 7008a5a0).
- Clean up Halvard-era Bedrock imports (POC 2 re-import, experiment imports) through the ledger once Phase 1b imports exist, keeping at most 3.
