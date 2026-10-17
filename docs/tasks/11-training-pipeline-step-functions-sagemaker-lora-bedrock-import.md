# Training pipeline: Step Functions, SageMaker LoRA, Bedrock import

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `2fd9c199-7f95-45ea-868f-ae36aeb88d90`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Train now → a new candidate model version in Bedrock.

## Scope
Reuse the proven POC code (`poc/sagemaker-bedrock`, POC 2 launcher). Data builder: training data from approved items per the spec's Training data recipe (Kimi K3 wordings, GLM-5 check, dedupe, overlap audit against dev and hidden sets; manifest + hashes to S3 and Box `reports/`). SageMaker training job on on-demand ml.g5.2xlarge (ml.g6.2xlarge alternate), pinned image digest, LoRA + merge in the same job, merged config capped at 32K, truncation guard. Step Functions Standard workflow: lock → build data → SageMaker (.sync) → CreateModelImportJob → Wait/GetModelImportJob poll loop with timeout → warm-up call → hand off to evaluation → promote or delete the import. Enforce ≤3 imports (base, current, candidate), deleting the oldest non-current one first. Record everything in the cleanup ledger. Hyperparameters from POC 2 (adjust if POC 2 recommends).
Not in scope: evaluation logic (call the evaluation task's entry point).

## Definition of Done
Tests for the data builder and state-machine definition (local or Step Functions test state); one live run produces a candidate import from the seeded pack.

## Verification
`make test`; `make train-live` (cost ≲ $1 GPU).

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Training transaction:** Train now takes the lock and freezes an **immutable approved snapshot** (hash) → data → SageMaker → import → evaluation → promote or reject → cleanup → release the lock, on **every** exit path (success, failure, timeout). Lock has an expiry and recovery. Submissions are idempotent (deterministic job names).
- **Hand-off to evaluation:** input = candidate ARN, snapshot hash, manifest hash, expected current version, dev-set hash; output = pass/fail, counts, report URI. Training owns conditional promotion (compare-and-set on the current version), cleanup and lock release; evaluation only returns the decision.
- **Gate rules:** the first version must beat the base on the dev set by a minimum gain (set in config); a tie means reject; any new failure on untold/unrelated dev questions means reject.
- **Imports:** reserve a slot in the cleanup ledger *before* CreateModelImportJob; take a live census before training; **only delete imports this deployment's ledger owns**. Never delete POC imports or "oldest non-current" by guess.
- The hidden-set overlap audit is **not** run here (see the Evaluation task); the builder never reads hidden content.
- DoD adds: tests for rejection cleanup, timeout cleanup, concurrent Train now (second is refused) and the slot ceiling under failure.


## Dev set (frozen 2026-10-17)
The dev set is `poc/model-experiment/data/dev.jsonl` (30 questions, 8 untold), SHA256 `5773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf`, commit 02d0857, audited against the hidden set, the addendum, the 386 training rows and itself. Reference it by path and hash; don't copy or edit it. The data builder must exclude it from training.


## Extraction interface (from the extraction task, 2026-10-17)
Use `ExtractionService.reviews()`, `.decide()` and `.snapshot()`. Never infer effective items from raw proposals. The effective items, review decisions and processed batches live in one revision-checked knowledge record (fails closed above 350 KB); immutable content-addressed snapshots are separate records, and training takes its snapshot from `.snapshot()`.

## Implementation started — 2026-10-17
Read the complete task, phase 1 overrides, frozen dev set and extraction interface. Help level LOW. Work limited to kloop/train/, training/ and training tests; shared-ledger extension coordinated with parent. Evaluation callable and API start/status interfaces agreed with parallel agents. No AWS/Box calls or resource creation; live spend $0. All three import slots are occupied by POC imports, which this deployment must not delete. Build against injected fakes first; live run remains coordinator-sequenced.

## Training implementation handoff — 2026-10-17T07:36Z

Task: 2fd9c199-7f95-45ea-868f-ae36aeb88d90. PR: none (not requested). Assignment base fc54528b717ff395977181c76b2c53f42a9a1a8b; immediate commit base e25a059d5d44af397cd3e6f50d41a30836580f3d; implementation head 7f6af711f0982e0fed5ca28471ff9539510b4a63; final head bdd954775977658627af12b8a343299288ae92d2 (evaluation owner requested the Makefile eval include).

Implemented:
- TrainingService.start(request_id, now), status(version_id), versions(); deterministic Standard execution names, atomic DynamoDB lock, immutable ExtractionService.snapshot() pin, current-version compare-and-set promotion.
- Approved-only data builder with Kimi wordings, independent batched GLM checks, all required recipe categories, provenance, dedupe, frozen-dev hash and lexical-overlap rejection, identical system prompt, content-addressed S3/Box manifest writer. The generator has no dev/hidden input; hidden audit stays in the dedicated evaluation Lambda.
- Configurable base ID/mirror/instance/hyperparameters, default Qwen3-4B + POC 2 settings. Digest-pinned on-demand SageMaker job; no local GPU execution; LoRA and full-weight merge in one job, 32K context, token truncation guard.
- Standard .sync training workflow, bounded import polling, warm-up, injected dev gate, conditional promotion/rejection, cleanup/release, failed/aborted/timed-out execution recovery and periodic expired-lock recovery for never-dispatched requests.
- Live census before GPU spend and again before import; ledger reservation before import/job creation, resolve last, uncertain reservations retained, only ledger-owned non-current imports deleted. Three foreign POC imports cause refusal, not deletion.
- ServingBackends protocol seam for warm_up/answer_with; Bedrock supplied, no alternate endpoint built.
- Training/evaluation Terraform wiring and separate evaluator-reader role; training worker cannot read sealed/ or assume the evaluator role.

Files touched: Makefile; infra/compute.tf, infra/training.tf, infra/training.asl.json; scripts/infra_build.py; kloop/cleanup.py; kloop/train/{__init__,config,data,helpers,job,job_request,live,resources,runtime,service,serving,state,worker,workflow}.py and commands.mk; tests/test_cleanup.py, tests/test_training.py. Shared-file changes were explicitly coordinated. No branch switch, push or PR; other agents' files were excluded.

Verification at 2026-10-17T07:35Z:
- make test && make lint: PASS, 279 tests; Ruff check and format PASS. One existing Starlette/httpx deprecation warning in the web test dependency.
- Training + cleanup subset: PASS, 45 tests. Covers immutable/hash/approval boundaries, dev leakage, duplicate/concurrent Train now, ambiguous and refused dispatch, CAS ownership, three foreign imports, pending slot/deletion failure, rejection, GPU timeout, failed submission, import timeout, successor-lock recovery, expired never-dispatched requests, ASL control flow and backend seam.
- terraform 1.13.4 validate and fmt -check: PASS.
- Read-only plan in an isolated /tmp copy using local backend and unchanged provider/resource configuration: PASS, 82 add / 0 change / 0 destroy. NO APPLY. The original checkout's saved backend points to the already-deleted wave-2 state bucket, so a normal backend plan cannot run until deploy/bootstrap selects a fresh backend; original backend configuration was not changed.
- make -n eval-live: PASS after the evaluation owner's requested include; no evaluation invoked.
- git diff --check: PASS. No CI run or PR exists for this task; no base CI failure link available.

Live train/evaluation: NOT RUN, as explicitly instructed. Resources created/deleted: none; live-run spend: $0. Original live DoD remains deferred to the coordinator's sequencing and available import capacity. Deploy must supply base import ARN, Box source/reports folder IDs and sealed evaluation objects, and finish the web/sync handler wiring owned by deploy. Report uploads currently follow the existing retained-report pattern (S3 in the Terraform-owned bucket; Box reports retained); coordinator has been asked to settle any additional per-file reservation/retention policy before live runs. Task-owned Terraform download/plan directory is removed after recording this handoff.


## Verification progress — 2026-10-17

Credential-free make test && make lint PASS (280 tests) at pushed 7e68a5b. Live-proof deviation confirmed in spec. Static and offline contract review found three runtime issues; structured fix request sent to original implementor and coordinator. Approval pending cache-miss bucket permission, SageMaker tagged-create permission, and training warm-up bound fixes. No product changes, no cloud calls or spend.

## Fix re-verification progress

Re-verification: all three fix diffs address the reported defects. Independent credential-free make test && make lint PASS (297 tests; 78 Python files formatted), and scoped git diff --check PASS. Runtime fake-clock tests cover seven-minute success and bounded failure, empty S3 cache generation/reuse, policy scopes and ASL synchronization. Terraform binary is not installed on verifier PATH, so independent Terraform validate was not run; implementor is running it. Fixes remain uncommitted in shared tree at time of test, so this is not yet pushed-head approval. Awaiting implementor publication; compare the five reviewed file hashes recorded in verifier tool output and test the published snapshot. No cloud calls, spending or verifier product edits.

## Exact-commit verification

Independent exact-commit re-verification PASS at a6f70b1e295e566f8653bac607af4f825bc90727, tree 25632f57b9ab984584d614bcf0c05f25023cdfd3. Credential-free make test && make lint in isolated /tmp git archive: 294 tests + Ruff check/format PASS. 36 training tests included factory wiring regression; all three defects resolved. git diff --check a6f70b1^ a6f70b1 PASS. Temporary archive/test environment removed automatically. Relevant task remains waiting only for publication: git ls-remote still reports 696c1db61e469702fac848cae1d16dbef7651c86, without the fix. Please push the fix (or acknowledge an explicit local-commit acceptance deviation); I can then complete immediately after confirming remote contains it. No cloud calls/spend, no product edits.

## Training verifier fixes — 2026-10-17T07:44:44Z

Fix request from training verifier agent-7a939e13-1676-4d33-9850-f3ddf34080f1, reviewing pushed 7e68a5b4232aa773b490321f4df7d7c9a1389287. Immediate base 9f11f5bfcfb68e929fa9648a4ea58df645a82cae; fix head a6f70b1e295e566f8653bac607af4f825bc90727; tree 25632f57b9ab984584d614bcf0c05f25023cdfd3. Task 2fd9c199-7f95-45ea-868f-ae36aeb88d90. PR none; commit is local and available for coordinator's combined push.

All three findings addressed:
- Worker now has ListBucket on the specific artifact bucket, enabling the documented 404 cache-miss path; object Get/Put remains limited to training/* and the role cannot assume the sealed-reader role. Empty-cache regression proves generation runs once and the second request uses the stored response. [S3 GetObject missing-key semantics](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html).
- Step Functions role now has AddTags only on deployment training-job ARNs, constrained by sagemaker:TaggingAction=CreateTrainingJob. [AWS tagging-on-create guidance](https://docs.aws.amazon.com/sagemaker/latest/dg/security_iam_id-based-policy-examples.html).
- Actual worker factory now selects a dedicated warm-up Answerer with 840-second retry budget, one SDK attempt, connect timeout 5s/read timeout 45s, with transport/overhead room inside the 900-second Lambda/ASL bound. Warm state increased from 300 to 900 seconds; generated JSON updated. Fake-clock regressions prove healthy seven-minute readiness succeeds, sustained cold starts fail within the bound (including long in-flight attempts), and the worker factory uses this client.

Files touched ONLY: infra/training.tf, infra/training.asl.json, kloop/train/runtime.py, kloop/train/workflow.py, tests/test_training.py.

Verification:
- Normal make test && make lint: PASS, 298 tests.
- Credential-free make test lint with AWS_PROFILE/access keys/session token unset, config and credentials files /dev/null, metadata disabled: PASS, 298 tests.
- uv run --locked pytest tests/test_training.py tests/test_cleanup.py -q: PASS, 51 focused tests.
- terraform 1.13.4 fmt -check and validate: PASS.
- git diff --check: PASS.
Full-suite runs used the shared working tree (other agents' unrelated uncommitted files were present); this is not a clean-checkout exact-head acceptance claim. The five owned files are committed unchanged from verification. Existing Starlette/httpx test dependency warning remains. No new CI run/PR or base CI failure link.

No live AWS/Box API, GPU, train or evaluation run, resource creation/deletion, or spend ($0). Per current spec, live seeded-pack proof is deferred to Phase 1b. Independent verifier approval is still pending. Task-owned /tmp/kloop-training-review-20261017 tooling is removed after this handoff.
