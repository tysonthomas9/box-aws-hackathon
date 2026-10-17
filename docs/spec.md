> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `spec`. Earlier progress entries are historical; later dated entries record updates.

## Goal
A 1–2 day demo, running entirely on **Box + AWS**, of a company that teaches its AI from its own Box documents and proves on a sealed hidden test set that the same model answers better after learning. **Hackathon scope: phase 1 MVP only** (LoRA on SageMaker, served on Bedrock). Phase 2 (TensorFold on an EC2 Mac) is deferred until after the hackathon.

Research: [Training methods compared](research/training-methods-compared.md) · [Demo scenarios](scenarios.md) · Source: /Users/tyson/codebase/code-agents/sept/references/enterprise-learning-ranking-and-funding-2026-10-16.md
## Decisions (updated 2026-10-17 after POCs and reviews)
- Use case: **company knowledge** for a fictional company, Halvard Systems. **Corpus frozen to the POC 2 pack** (10 facts, 3 procedures, E42 = pump/inlet-pressure rule) plus a v2 edit that uses existing items (one changed value, one retirement).
- **Nothing runs on the laptop.** Box is the document store; every AWS resource is in **us-east-2** (profile `box-hackathon`). Exception: Kimi K3 is called through its US cross-region inference profile (approved by Tyson). Code lives in this repo and deploys with one command.
- **Languages:** Python 3.12 + uv for all application, Lambda, training and eval code; Terraform for infrastructure; web UI: **OpenUI chat interface (React, static export built inside `make deploy`)** for Ask, replacing the plain HTML page (Tyson, 2026-10-17).
- **Login:** one shared password (Secrets Manager). `/api/login` is public, `/api/box-webhook` is checked by signature only, and every other route needs the signed cookie. Origin/CSRF check and throttling.
- **Box auth:** CCG app (credentials in Secrets Manager `box-hackathon/box-ccg`) plus a developer token for testing. A separate Box OAuth app is built only if CCG authorization proves impossible. Webhook events are rejected until signing keys exist.
- **Model choice under test (2026-10-17):** a model experiment compares Qwen3-4B vs Qwen3-8B on training data v2 with many more "I don't know" and near-miss cases, chosen on a separate dev set. Phase 1 adopts the winner.
- **Base model:** Qwen3-4B-Instruct-2507, **every import capped at 32K context** (the 262K import never served). Same model for "without" and "with". Fallback: Qwen3-8B.
- **Training:** on-demand ml.g5.2xlarge (ml.g6.2xlarge as the alternate; 1 each approved). LoRA → merge in the same job → S3 → Bedrock Custom Model Import. **Train now** button only, with a lock; every version retrains from base on the full approved set.
- **At most 3 imports** (base, current, candidate); others are deleted immediately.
- **Helper models on Bedrock:** Kimi K3 (US inference profile, approved by Tyson) writes training data; GLM-5 judges answers (blinded) and is the extraction fallback. No direct Bedrock Claude use; Box AI's pinned extraction model is AWS-hosted Claude Haiku inside Box.
- **Extraction:** Box AI `extract_structured`, one file per call, pinned model, table fields for lists.
- **Sync:** Box webhook (signature-verified, deduped on event id) + 1-minute schedule + Sync now.
- **Review:** automatic checks; only flagged items, changed values and retirements wait for a person.
- **Evaluation:** code checks + GLM-5 judge. Dev set for the promotion gate; sealed, hashed hidden set for the reported score and kept apart from data builders. Bedrock Evaluations is dropped (optional later).
- **Ask:** asynchronous per-mode jobs (SQS worker) with polling; each job pins its model ARN and snapshot (API Gateway times out at 30 s; cold start ≈3 min), plus a Warm up button.
- **Training transaction:** immutable approved snapshot → train → import → blinded dev-set evaluation → compare-and-set promotion or rejection → cleanup → lock release on every exit. Only imports in this deployment's cleanup ledger are ever deleted.
- **API path:** CloudFront → API Gateway default endpoint (kept enabled) with a secret origin header; no custom domain.
- **Live demo:** live Box edit → webhook → extraction → review; then switch to a pre-trained version 2 (disclosed), not a live retrain.
- **Standing rules:** no AWS Support cases or quota requests without asking Tyson; stop before any single action > $10; no rm outside /tmp without asking; no Claude attribution in commits.
## Architecture
```text
+---------------------------- BOX ---------------------------------+
|  Halvard folder (docs)       |  reports/ (manifests, eval reports)|
|  Box AI extract_structured   |  Webhooks v2 (signed)              |
+------+-----------------------------------------------^------------+
       | webhook                                       | Box SDK (CCG)
       v                                               |
+------------------------------ AWS us-east-2 ----------------------+
|  CloudFront -> S3 static UI (Sources | Review | Ask | Results)     |
|  CloudFront /api -> API Gateway -> API Lambda (shared password)    |
|       /api/box-webhook -> Sync Lambda <- EventBridge (1 min)       |
|                              |  (also Sync now)                    |
|                              v                                     |
|            Extract (Box AI; GLM-5 fallback) + automatic checks     |
|                              v                                     |
|            DynamoDB: items, reviews, versions, jobs, cursors       |
|                              |  Train now (locked)                 |
|                              v                                     |
|  Step Functions: build data (Kimi K3) -> SageMaker LoRA + merge    |
|    -> S3 -> Bedrock import (start / wait / poll) -> eval (GLM-5)   |
|    -> dev-set gate -> promote, or delete import                    |
|  Bedrock: Qwen base "without" | Qwen + LoRA vN "with" (32K cap)    |
|  Ask jobs: Lambda per mode, results polled by the UI               |
|  Terraform manages all of it; cleanup ledger for imports/webhook   |
+-------------------------------------------------------------------+
```
## How it runs end to end
1. **Change:** someone edits a file in Box; the webhook (or the schedule, or Sync now) starts a sync.
2. **Sync:** compare file versions with the last sync; skip unchanged files; retire items from deleted files.
3. **Extract:** Box AI pulls facts and procedures, with supporting quotes, from each new or edited file.
4. **Check and review:** clean items are approved automatically; flagged items, changed values and retirements wait on the Review screen.
5. **Train now:** Step Functions builds the training data, trains and merges on SageMaker, imports to Bedrock and waits until ready.
6. **Gate:** the candidate is scored on the dev set and promoted only if it beats the current version with no new failures; otherwise its import is deleted.
7. **Compare:** Ask shows without / with / search for any question; Results shows the sealed hidden-set scores by question type; manifests and reports are copied to Box `reports/`.
## Training data
Rebuilt from scratch from the current approved items for every version, stored in S3 with a manifest (also copied to Box). Recipe proven in POC 2: Kimi K3 writes wordings, GLM-5 checks them, then dedupe and an overlap audit against the hidden set.
- **Fact Q&A:** about 10 wordings per fact; answers come from the approved item.
- **Procedure cases:** 6–8 situations per procedure covering both branches.
- **"I don't know":** Halvard questions the documents don't answer.
- **Near misses:** wrong person, product or value.
- **General replay:** ordinary instruction data, to prevent the collapse seen in POC 1's tiny run.
Settings from POC 2: 3 epochs, LR 2e-4, max length 512 (with a truncation guard), seed fixed. Kept out of training: every hidden-set wording, hidden procedure situations and two-fact questions. The same system prompt is used for training and every test mode. A learned "(Source: file)" is training lineage, not a citation; only search mode gives real citations.
## Open unknowns (the "fog")
| # | Unknown | Status |
|---|---|---|
| 1 | SageMaker GPU quota | **Resolved:** g5/g6.2xlarge = 1 each |
| 2 | Bedrock import time, cold start, billing | **Resolved:** ~12 min import, ~3 min cold start, 1 CMU with the 32K cap |
| 3 | InvokeModel payload / chat template | **Resolved:** in the POC 1 runbook |
| 4 | Helper models | **Resolved:** Kimi K3 + GLM-5 work (Claude not needed) |
| 5 | Does a small LoRA learn facts / procedures? | **Answered:** facts yes (20/20), two-fact no (1/5), abstention regressed (2/10) |
| 11 | Why the POC 2 trained import never starts in Bedrock | **Resolved 07:19 UTC:** a re-import of the exact same weights (`imported-model/ol1fd5dnxm6w`) served on its 4th cold-start attempt, so it was a one-off Bedrock failure. Mitigation: the training pipeline retries the import once if the model never becomes ready. |
| 6 | Training cost | **Resolved:** ~$0.13–0.20 per run |
| 7–8 | Box AI access and extraction quality | **Resolved:** 3/3 items, 6/6 obligations |
| 9 | CCG authorization, webhook signatures | **Resolved:** CCG authorized and signing in as the app's service account; webhook signing keys stored in `box-hackathon/box-ccg` (07:27 UTC). Live signed delivery is tested in the deploy wave. |
| 10 | TensorFold on EC2 Mac | Deferred (phase 2) |
## Review findings
Reviews: [Claude](reviews/architecture-review-claude.md) (ship with changes) and Codex (rethink). Applied to the decisions and phase 1 tasks on 2026-10-17, then a [Phase 1 plan review](reviews/phase-1-plan-review.md) (ship with changes) found them only partially applied; its changes are appended to each task under "Changes from the phase 1 plan review". Scenario 5 now gives the held-out rule in the question, testing the habit rather than unknowable facts.
## Tasks

### Phase 0: POCs (do first; each answers one unknown, throwaway code allowed)

- [x] [POC 1 — AWS learning path: SageMaker LoRA to Bedrock import](tasks/01-poc-1-aws-learning-path-sagemaker-lora-to-bedrock-import.md)

- [x] [POC 2 — Does a small LoRA actually learn company knowledge?](tasks/02-poc-2-does-a-small-lora-actually-learn-company-knowledge.md)

- [x] [POC 3 — Box CCG app, Box AI extraction and webhook delivery](tasks/03-poc-3-box-ccg-app-box-ai-extraction-and-webhook-delivery.md)

### Phase 1: Box + AWS managed LoRA (after POCs)

- [x] [Scaffold repo layout and shared schemas](tasks/04-scaffold-repo-layout-and-shared-schemas.md)

- [x] [Terraform foundation and deploy commands](tasks/05-terraform-foundation-and-deploy-commands.md)

- [x] [Box client: CCG auth, files, versions, seeding](tasks/06-box-client-ccg-auth-files-versions-seeding.md)

- [x] [Fictional company knowledge pack](tasks/07-fictional-company-knowledge-pack.md)

- [x] [Box AI extraction, automatic checks and review](tasks/08-box-ai-extraction-automatic-checks-and-review.md)

- [x] [Box sync service: webhook, schedule and Sync now](tasks/09-box-sync-service-webhook-schedule-and-sync-now.md)

- [x] [Answering library: without, with, and search](tasks/10-answering-library-without-with-and-search.md)

- [ ] [Training pipeline: Step Functions, SageMaker LoRA, Bedrock import](tasks/11-training-pipeline-step-functions-sagemaker-lora-bedrock-import.md)

- [x] [Evaluation with Bedrock judge, Evaluations jobs and promotion gate](tasks/12-evaluation-with-bedrock-judge-evaluations-jobs-and-promotion-gate.md)

- [x] [Web app on AWS: API, shared-password login and screens](tasks/13-web-app-on-aws-api-shared-password-login-and-screens.md)

- [ ] [Deploy, seed and demo runbook](tasks/14-deploy-seed-and-demo-runbook.md)

### Phase 2: TensorFold facts

- [ ] [Phase 2: TensorFold feasibility on EC2 Mac](tasks/15-phase-2-tensorfold-feasibility-on-ec2-mac.md)

- [ ] [TensorFold fact teaching and Box sync](tasks/16-tensorfold-fact-teaching-and-box-sync.md)

- [ ] [Phase 2: add the TensorFold track to inference, evaluation, UI and demo](tasks/17-phase-2-add-the-tensorfold-track-to-inference-evaluation-ui-and-demo.md)

## Execution waves
**Phase 1 MVP**
1. Scaffold.
2. In parallel: Terraform foundation, Box client, knowledge pack, answering library.
3. In parallel: extraction + checks + review, sync service, training pipeline, evaluation.
4. In parallel: web app, then deploy / seed / demo runbook.

**Quality gates per wave:** each task gets its own verifier (scope, Definition of Done, tests re-run, no secrets, no cross-task edits), and each wave's combined diff gets a code review (correctness, security, AWS/Box misuse). The next wave starts only when all of a wave's verifiers approve and its review findings are fixed or explicitly deferred. After wave 4, an end-to-end check: deploy, seed, smoke, the unattended run, then destroy. Phase 2 (TensorFold) is deferred.
## Acceptance Criteria
- From a fresh project: `make bootstrap && make deploy && make seed` gives a working URL; `make destroy` removes everything, including Bedrock imports and the Box webhook (cleanup ledger).
- Nothing in the running system depends on the laptop.
- Only `/api/login` is public; the Box webhook is accepted only with a valid signature; everything else needs the shared-password cookie.
- A Box edit becomes review items within 60 seconds via the webhook (measured), and within 3 minutes via the schedule if the webhook is off.
- Clean items are approved automatically; the v2 edit flags exactly its changed value and its retirement; an unchanged re-sync changes nothing.
- Train now runs the full training transaction in Step Functions; rejection, failure and timeout all clean up and release the lock; a second Train now is refused; never more than 3 imports; POC imports are untouched.
- Ask shows the same Qwen model without and with learning, plus search, via asynchronous jobs, so no request hits the 30 s limit.
- Results shows hidden-set scores by question type for all three modes with paired raw counts, all bound to the same corpus, prompt and model versions plus the audit hash, and the honesty caveats (exploratory set, lexical audit only).
- An unattended run (sync → Train now → Ask) completes with the laptop disconnected.
- `make test` passes without AWS or Box credentials.
## Non-goals
- Phase 2 / TensorFold during the hackathon.
- Proving business value (fictional data proves the mechanism only).
- User accounts, Cognito, production hardening, multi-tenant.
- Live retraining during the demo; automatic training triggers.
- Bedrock Evaluations jobs, DPO or RL.
## Assumptions
- Region us-east-2, AWS profile `box-hackathon` (new AWS experience, Free plan with credits).
- Tyson authorizes the Box CCG app and generates webhook signing keys before phase 1 deploy (otherwise use the OAuth fallback, and test signatures when the keys exist) (confirm?).
- POC 2 shows a useful learning gain; if not, the training-data recipe is adjusted before the training-pipeline task finishes (confirm after POC 2).
## Verification Plan
- `make test`
- `make deploy && make seed && make smoke`
- Open the URL, log in, walk the demo runbook
- `make destroy`

## Rollback Plan
All work is on branch withered-cobra. `make destroy` removes the AWS stack, Bedrock imports (cleanup ledger) and the Box webhook; the Terraform state bucket is removed last.
## POC results

**POC 1: AWS learning path. Mechanics PASS (2026-10-17).** SageMaker LoRA → merge → Bedrock Custom Model Import → InvokeModel works entirely on AWS. Imports must cap context at 32K: the 262K-context import never served, while the 32K one serves on 1 CMU. Import takes ~12 min; cold start ~2.5–3 min; a warm call takes <1 s. A tiny 20-example run costs ~$0.13 of GPU and peaks at 8.8 GB GPU memory. The tiny run overfit (it answered every question with its one taught phrase), so quality must be judged by POC 2. Kept: the 32K base `imported-model/0inmdc8ttj1w` and the S3 weight mirrors. Evidence: commits ad5f261, 7250aa7.

**POC 2: learning signal. Verdict ADJUST (2026-10-17).** LoRA (served via SageMaker/transformers because the Bedrock import never started) scored **39/52** vs base 22/52 and search 49/52: single facts **20/20** (base 0/20), two-fact 1/5, procedures 6/7 (possibly over-credited), unrelated 10/10 (no forgetting), but **"I don't know" 2/10: it invented answers 8 times** (base 10/10). Search stays the authoritative mode; the LoRA learns facts on new wordings but needs many more abstention / near-miss examples. Results: [POC 2 note](pocs/poc-2-results.md), commit d9ae15e. Earlier progress: 386 Kimi K3 rows, GLM-5 approved, overlap-clean (0beb118). Sealed hidden set: 46 questions + 6 procedure questions (a300cd5). Baseline: base 22/52, base+search 49/52 (facts 0/20 vs 19/20; procedures 2/7 vs 6/7). The LoRA run on ml.g6.2xlarge is next.

**POC 3: Box. PASS with a developer token (2026-10-17).** Box AI `extract_structured` (pinned AWS-hosted Claude Haiku model, table fields) recovered 3/3 gold items and 6/6 obligations across 3 uploaded docs; a real webhook arrived 1.6 s after upload. All test resources deleted. Evidence: 4bbf06c, [POC 3 runbook](pocs/poc-3-runbook.md). **Open for phase 1:** CCG app admin authorization (fallback: Box OAuth app with a stored refresh token) and webhook signing keys (signature verification not yet tested). Credentials are in Secrets Manager `box-hackathon/box-ccg`.

## Operating rules while Tyson is away (2026-10-17, ~8 h)

- Coordinator continues phase 1 waves 3–4, then runs the [Demo end-to-end test](tasks/18-demo-browser-test.md).
- Advisors: **Astra** (Codex gpt-6-astra) and **Fable** (Claude Fable) are consulted on blockers and go/no-go calls; when they disagree, choose the safer, cheaper option and record why.
- Coordinator picks the phase 1 model (4B vs 8B) and recipe from the model experiment's dev-set results; **if undecided by 09:00 UTC, lock Qwen3-4B.**
- **Bedrock serving deadline 08:30 UTC:** if no trained import has served on Bedrock by then, the 'with' mode falls back to a non-Bedrock serving path (decided with the advisors), with the runtime difference disclosed.
- **Cold-start bounds (Fable, 07:22 UTC):** when two imports load at the same time, cold start took ~7 min instead of ~3 (CloudWatch). Warm-up and Ask readiness bounds are 15 min, and Warm up loads the base and trained models one after the other, not in parallel.
- **Backup serving path** (only if Bedrock stops serving trained imports): a SageMaker real-time GPU endpoint behind the existing async Ask worker. Applied endpoint quota is ml.g6.xlarge=1, ml.g6.2xlarge=1, ml.g5.xlarge=2, ml.g5.2xlarge=2; about $9–12 for 8 h (g6.xlarge for 4B). EC2 GPU quota is 0. Advice from Astra, 07:21 UTC.
- Import slots: base + at most one trained import while experimenting; the duplicate x2feesmws1lw is deleted after the re-import test.
- Budget: total new spend ≤ $40 during this period, still ≤ $10 per single action; no Support cases or quota requests; no new paid plans.
- Deploy the full stack in us-east-2 and leave it running for Tyson's demo (idle cost is small; Bedrock imports scale to zero).
- Anything needing Tyson (Box console, AWS sign-in, money beyond the cap) is recorded under "Waiting on Tyson" in this spec rather than blocking other work.

## Phase 1b — redo the pipeline on the medical company corpus

**Goal:** the demo learns from Tyson's real Box folder "The Rubber Ducks" (id 428390666255, a synthetic mRNA-vaccine company; Tyson confirmed the documents are synthetic, no real patient data) instead of the fictional Halvard pack.

**Decisions (2026-10-17, Tyson):** use The Rubber Ducks as the demo source; redo the whole pipeline on it. The app's service account has Editor access (verified). The folder is owned outside our Box enterprise (vyshnaviburle@gmail.com).

**Assumptions:**
- Training, dev and sealed test sets come from `company-specific/` only (about 130 Word documents: clinical, commercial/HEOR, pharmacovigilance, quality/manufacturing, regulatory). (confirm?)
- `public/` (FDA, ICH, SEC filings) is left out of Phase 1b entirely (not trained on, not searched): the base model already knows much of it, it is large, and search only covers approved items. (confirm?)
- The 4B vs 8B decision from the running model experiment carries over; Phase 1b trains only the winner.
- Box AI and webhooks work on a folder owned by another enterprise. Task 1b-1 proves this first.
- Phase 1b spend is at most $20 inside the existing $40 AFK budget.
- **Training corpus cap (07:43 UTC):** the folder has 115 Word documents and Box AI finds about 25 items in each (~2,900 total). Training on all of them would take many hours, so the training snapshot is capped at about 300–400 items (at most ~4 per document, preferring specific checkable facts and one rule per SOP). Every item stays stored and searchable. Probe so far: webhook permission on the other-enterprise folder PASS; Box AI reads Word files natively PASS.
- Storage now holds items as separate rows and the snapshot body in S3, because the old design capped stored knowledge at 350 KB.

**Non-goals:** medical advice; real patient data; training on `public/`; retraining live on stage.

**Model size decision (runs now, in parallel):** [Model experiment: 4B vs 8B](experiments/model-comparison.md) trains both on the improved data (more "I don't know" and near-miss rows), imports each to Bedrock and scores them on the dev set. Rule: pick 8B only if it clearly beats 4B on the dev set, especially on "I don't know" questions, without new failures; otherwise 4B. If undecided by 09:00 UTC, lock 4B. Task 1b-3 trains only the winner. Status 07:42 UTC: 4B training finished (831 s); 8B still training.

**Chat UI (Tyson, 07:42 UTC):** the Ask screen uses OpenUI's MIT-licensed chat interface with fixed answer cards built by our code. No generative layout, no second model rewriting answers, no OpenUI Cloud. open-intelligent-ui has no license, so its code is used only as visual reference.

- [/] [1b-1 Medical corpus: sync, extraction and approved snapshot](phase-1b/01-medical-corpus.md)

- [ ] [1b-2 Medical dev set, sealed test set and demo scenarios](phase-1b/02-dev-and-hidden-sets.md)

- [ ] [1b-3 Train, import and evaluate on the medical corpus](phase-1b/03-training-and-evaluation.md)


## Acceptance deviation: wave 3 live proof (2026-10-17)
Wave 3 tasks are accepted on credential-free proof: code, tests and lint pass, plus the evaluation agent's live dev and hidden runs. Live proof of the CloudFront screens, the real three-mode comparison in the UI and a forced cold start move to the deploy task (f8eca485) and the demo e2e browser test (5e5b5496). The training task's live seeded-pack candidate import is replaced by Phase 1b task 1b-3 (train and import on the medical corpus). Verifiers approve wave 3 on that basis.

- [/] [1b-UI OpenUI chat interface for Ask, with fixed answer cards](phase-1b/04-openui-chat.md)

**Phase 1b gates:** each 1b task gets a verifier, and the Phase 1b changes together get one Codex code review, before deploy.

**Remaining after Phase 1b:** [Deploy, seed and demo runbook](tasks/14-deploy-seed-and-demo-runbook.md) (now for the medical folder), then [Demo end-to-end browser test](tasks/18-demo-browser-test.md).

- [/] [Sync docs to the ideas branch](intent://local/task/956b4ef7-3d6c-47f6-962f-a5412ff2af31)
