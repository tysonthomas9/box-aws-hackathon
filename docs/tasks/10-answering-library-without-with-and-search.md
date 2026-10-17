# Answering library: without, with, and search

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `c4340023-318c-4661-8059-6c572d03060e`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

One function per answer mode, used by Ask jobs and evaluation.

## Scope
`kloop/answer/`: Bedrock InvokeModel for imported Qwen3 using the exact payload and chat template from the POC 1 runbook (`poc/sagemaker-bedrock`); the same system prompt as training; fixed decoding. Modes: **without** (base import), **with** (current promoted import), **search** (base import + top-k chunks from the approved documents, simple BM25 or embeddings with Titan; gives real citations). Cold-start handling: retry ModelNotReadyException with backoff up to ~4 min, report a "warming" status; a warm-up call. Return answer, latency, model ARN, citations (search only).
Not in scope: the HTTP API.

## Definition of Done
Tests with a fake model client; a live smoke answers one question in each mode against the 32K base import.

## Verification
`make test`; `make answer-smoke`.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Inference only:** job lifecycle belongs to the Web app task.
- **Search = BM25 only** over approved documents (no Titan embeddings).
- Accepts an explicit model ARN per call (pinned by the job).
- DoD smoke uses the base AND a trained candidate ARN (POC 2's retained import `x2feesmws1lw` is fine).

## Implementation progress
Added SDK-free Answerer modes, pinned explicit model ARN, POC system/template/decoding, BM25 versioned chunks/citations, bounded cold-start retries plus warming callback and warm-up. Initial make test: 38 PASS. Initial live smoke exposed missing botocore CRT dependency for the social-login AWS profile; coordinating the dependency extra with the Box client agent who currently owns pyproject/uv.lock.

## Checkpoint — 2026-10-17T06:31Z
Commit 8eb7660b201b4670b61c684119ea84c33fb5c23b contains only kloop/answer/__init__.py, kloop/answer/bedrock.py, kloop/answer/smoke.py, tests/test_answer.py. Scoped lint/format and make test PASS (38 tests). Full make lint sees four line-length findings in the Box agent’s in-progress files; owner notified, no baseline failure claim. Makefile answer-smoke target is being committed with the Terraform agent’s concurrent Makefile edits; boto3[crt] login dependency is being committed by the Box agent with its dependency edits.
Initial make answer-smoke failed before inference because login credential provider lacked CRT. Temporary uv --with botocore[crt] smoke is running (exec session 88554, Python PID 95998): without answered unknown against base 0inmdc8ttj1w; trained x2feesmws1lw is warming under the tested four-minute retry budget. No created or deleted AWS resources. FREE plan ACTIVE; configured Region us-east-2.
Fetch found no remote commits missing locally. Required pull --rebase was attempted but refused because other agents have unstaged shared-checkout changes; no stash/branch switch was performed.

## Live readiness finding — 2026-10-17T06:35Z
First trained smoke exhausted the full 240-second warming budget with ModelNotReadyException; no trained answer. POC2 owner independently reports zero successes in 11 checks over ten minutes and sealed readiness failure at dc70b0a. Standard make answer-smoke rerun is now using the fixed login dependency; base itself is warming after idle expiry. A separate search-only live check is running to avoid skipping search due to trained unavailability. No code/provider fallback or resource changes.
Latest full make test PASS:82 tests including concurrent Box/cleanup work; make lint PASS:27 formatted files. Base SHA CI query returned [] (no CI run link).

## Stop overlapping candidate checks — 2026-10-17T06:36Z
POC2 owner requested stopping overlapping candidate loops. Stopped exact owned standard smoke Python PID4398 before candidate mode: it was still warming the idle-expired base, so standard make smoke ended143 by intentional termination (not an inference failure). No candidate retry remains. Kept independent base search process (uv PID5165, exec12571) only. Existing standard smoke output is retained temporarily in two owned /tmp files until final evidence is sealed. No code changes.

## Final answering handoff — 2026-10-17T06:37Z
Task c4340023-318c-4661-8059-6c572d03060e. Implementation commit 8eb7660b201b4670b61c684119ea84c33fb5c23b is pushed on withered-cobra; shared head/origin now 99a0bc1e31da4dc8030548350c89d35ab1052619. Base 14a9d4a54c896116458b97b5301bd4e04fae33e0. No PR exists yet (gh pr view); no base CI runs (gh run list returned []). Files: kloop/answer/__init__.py, kloop/answer/bedrock.py, kloop/answer/smoke.py, tests/test_answer.py. Makefile answer-smoke target is present but still uncommitted with Terraform owner's shared edits; owner explicitly committed to preserving/committing it. boto3[crt] dependency is committed with Box changes 0468f13.

Implemented Answerer.answer_without(question, explicit_model_arn), answer_with(question, explicit_model_arn), answer_search(question, explicit_base_arn, approved_documents, top_k=3), warm_up(model_arn). Use ImportedModelClient wrapping the injected us-east-2 Bedrock runtime client; disable SDK retries so Answerer owns the 240s budget. on_status emits warming without mutating job state. Result contains answer, latency_ms, model_arn, and only referenced retrieved citations. Caller supplies an approved document snapshot and pins model versions. Training producer should reuse SYSTEM_PROMPT. BM25 chunks are 180 words with30 overlap; each citation pins file/version/name/exact quote/offsets.

Gates: make test PASS38 immediately after implementation, then PASS82 in shared checkout at06:35Z. Scoped ruff and full make lint PASS; git diff --check PASS. Canonical no-tools Qwen template, max_gen_len256, temperature0; warm-up max_gen_len16. Fake tests cover prompt/ARN pinning, BM25 ordering/chunks/empty matches, citation provenance, cold success/status/latency and budget exhaustion, malformed outputs, wrong Region/model and non-warming error propagation; Stubber checks native request/error mapping/body closure.

Live base without PASS at06:30:47Z: "I do not know who owns the Kestrel service.", 581.43ms, base0inmdc8ttj1w; no citations.
Live independent search PASS (finished by06:37:32Z): "The Kestrel service is owned by Mira Solven [1].", 115081.61ms including cold start, same base ARN. Citation: label1, file_id F01, version_id poc2-frozen, name kestrel.txt, quote "The Kestrel service owner is Mira Solven.", offsets0:41. This smoke uses the approved POC fixture, not live Box approval integration.
Live trained with BLOCKED: x2feesmws1lw returned ModelNotReady throughout240s. POC2 independently sealed zero successful responses across11checks/ten minutes (dc70b0a). Full three-mode Definition of Done remains unmet; no trained-answer or quality claim. Initial normal make smoke lacked CRT dependency (fixed); second normal smoke intentionally stopped on POC2 owner's request before its candidate call, while base was warming: inner process143, make exit2, not a payload failure. Its raw log: make command; six {"status":"warming"} lines; make Error143.

Rerun once the coordinator resolves candidate readiness:
KLOOP_BASE_MODEL_ID=arn:aws:bedrock:us-east-2:549803795565:imported-model/0inmdc8ttj1w KLOOP_SMOKE_TRAINED_MODEL_ARN=arn:aws:bedrock:us-east-2:549803795565:imported-model/x2feesmws1lw make answer-smoke
No candidate retries or active hooks remain. FREE plan ACTIVE and selected Region us-east-2 verified. No created/deleted AWS resources; retained imports unchanged. No Support/quota requests. Own two /tmp smoke files will be deleted after this record; AGENTS.md/CLAUDE.md and other tasks' work untouched. Pull --rebase was attempted and refused concurrent unstaged changes; fetch confirmed no missing remote commits, own implementation pushed successfully.

## Verifier findings — answering library, 2026-10-17

### Verification Summary
- Verdict: ✅ APPROVED under the coordinator's revised acceptance.
- Confidence: High for code and offline gates; live base results are retained implementor evidence, not fresh verifier invocations.
- Reviewed/tested head: 891b5a543b50bb961cecfc228a2451de3a89462b on withered-cobra. Scaffold base: 14a9d4a54c896116458b97b5301bd4e04fae33e0. Answer implementation: 8eb7660b201b4670b61c684119ea84c33fb5c23b.
- Coordinator explicitly revised this assignment: defer trained-ARN live smoke because x2feesmws1lw never becomes ready; accept successful live base without/search plus unit-tested explicit trained ARN support. This supersedes the earlier task smoke requirement. No unresolved spec ambiguity or failing criteria.

### Acceptance Criteria Checklist
- ✅ VERIFIED: Inference-only functions for without, with and search; explicit model ARN per call.
  - Evidence: kloop/answer/__init__.py Answerer methods; implementation commit 8eb7660.
  - Verification: test_modes_pin_model_and_use_training_prompt_and_fixed_template passed with distinct BASE/TRAINED ARNs and exact request assertions. No API/job lifecycle writes.
- ✅ VERIFIED: Imported Qwen native payload, canonical no-tools template, training system prompt and fixed decoding.
  - Evidence: _answer builds system/user/assistant template, max_gen_len=256, temperature=0; existing native BedrockModelClient adapter invokes the pinned ARN.
  - Verification: prompt/template/decoding assertions and equality to POC2 pack.system_prompt passed; adapter Stubber request and body closure tests passed.
- ✅ VERIFIED: Search uses BM25 over supplied approved documents and returns real versioned citations.
  - Evidence: retrieve uses BM25 k1=1.5/b=.75, 180-word chunks/30 overlap; Citation includes file/version/name/exact quote/start/end. Only retrieved labels referenced by the model become citations.
  - Verification: ranking/ties, later-chunk retrieval, exact offsets, empty/no-match, uncited output and invented label checks passed. No Titan/embedding calls. Approval snapshot selection remains caller-owned as specified.
- ✅ VERIFIED: Bounded warming retries/status plus warm-up.
  - Evidence: ModelNotReady maps to ModelWarming; only that exception retries with 2s exponential backoff capped at20s and240s budget; callback emits warming; warm_up requests16tokens.
  - Verification: fake clock success/status/latency and240s exhaustion passed; other errors propagate; Region and ARN rejection tests passed. In-flight request duration is bounded by caller transport settings; smoke disables SDK retries and sets5s connect/30s read timeouts.
- ✅ VERIFIED: Answer, latency and model ARN returned; citations only for search.
  - Evidence: Answer schema and _answer result construction.
  - Verification: mode, prompt, citation and latency assertions passed; without/with learned source strings return an empty citations list.
- ✅ VERIFIED: Revised live smoke criterion: base without/search passed; explicit trained ARN supported and unit-tested; trained runtime deferred.
  - Evidence: task Final answering handoff at06:37Z and matching PR context: base0inmdc8ttj1w without returned unknown at581.43ms; independent search returned Mira Solven [1] at115081.61ms including cold start, F01/poc2-frozen/kestrel.txt quote offsets0:41. Implementor conversation cross-checked. Fixture smoke is not live Box integration proof.
  - Verification: reviewed retained results; no new paid inference invoked. TRAINED ARN selection test passed in this verifier's run. Full make answer-smoke was not rerun because it invokes the deferred candidate and prior owner stopped overlapping retries.
- ✅ VERIFIED: Tests/lint, no committed secrets in task scope, no unauthorized cross-task edits.
  - Evidence: git show8eb7660 lists exactly kloop/answer/{__init__,bedrock,smoke}.py and tests/test_answer.py. Coordinated Makefile target is committed in891b5a5; boto3[crt] in0468f13 with dependency owner.
  - Verification: make test && make lint passed85tests (17answer cases), ruff check and28-file format check. git diff --check scaffold..head clean. Read-only credential-pattern scan over all added history since scaffold in answering files and declared shared files found zero findings; manual review found only fake test credentials, no secret values. Other wave-two commits belong to other tasks and are not approved by this task verdict.

### Evidence index
- Commits reviewed: 8eb7660 answering; shared integration0468f13 and891b5a5; tested head891b5a543b50bb961cecfc228a2451de3a89462b.
- Notes reviewed: c4340023-318c-4661-8059-6c572d03060e in full including plan-review overrides; PR context846fb942-136d-4b81-98f2-354a4926f1de; spec Goal/Decisions/Non-goals/Acceptance Criteria/Verification Plan.
- Files/areas: all answering sources/tests, Makefile, pyproject.toml/uv.lock changes, existing schemas/native adapter/test fixtures and POC prompt/payload evidence.

### Tests/Commands Run
- make test && make lint → PASS:85tests in1.58s; ruff check PASS;28files formatted.
- git diff --check 14a9d4a HEAD → PASS.
- git show --name-only --format= 8eb7660 → PASS scope:exactly4declared files.
- git log over answering/shared paths since scaffold → coordinated changes only.
- Read-only Python credential-pattern scanner over git log -p for answering/shared paths → zero findings (no matched values printed).
- git status --short → no tracked edits; pre-existing untracked AGENTS.md,CLAUDE.md,POC2status artifact left untouched.
- make answer-smoke → NOT RERUN: trained live invocation explicitly deferred by coordinator. Prior base without/search PASS evidence reviewed.

### Exact re-verify commands
```sh
git rev-parse HEAD
make test && make lint
git diff --check 14a9d4a54c896116458b97b5301bd4e04fae33e0 HEAD
git show --name-only --format= 8eb7660b201b4670b61c684119ea84c33fb5c23b
git status --short
```
After the coordinator resolves readiness and authorizes the deferred smoke:
```sh
KLOOP_BASE_MODEL_ID=arn:aws:bedrock:us-east-2:549803795565:imported-model/0inmdc8ttj1w KLOOP_SMOKE_TRAINED_MODEL_ARN=arn:aws:bedrock:us-east-2:549803795565:imported-model/x2feesmws1lw make answer-smoke
```

### Risk Notes
Trained Bedrock runtime remains unproven and is an accepted infrastructure deferral, not a passing trained inference or quality claim. Citation provenance does not prove every generated claim is supported. No AWS/Box calls, deploys, resource changes, code fixes or commits made by this verifier.
