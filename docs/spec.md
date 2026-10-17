## Goal
A 1–2 day demo, running entirely on **Box + AWS**, of a company that teaches its AI from its own Box documents and proves on a hidden test set that the same model answers better after learning. **Phase 1:** LoRA on SageMaker, served on Bedrock. **Phase 2:** TensorFold fact insertion on an EC2 Mac.

Research: [Training methods compared](research/training-methods-compared.md) · [Demo scenarios](scenarios.md) · Source: /Users/tyson/codebase/code-agents/sept/references/enterprise-learning-ranking-and-funding-2026-10-16.md

## Decisions (2026-10-16)
- Use case: **company knowledge** for a fictional company, Halvard Systems.
- **Nothing runs on the laptop.** Web app, sync, extraction, training, evaluation and serving all run on AWS; Box is the document store. Code lives in this repo and deploys with one command.
- **Infrastructure as code: Terraform**; `make deploy` / `make destroy`.
- **Login: one shared password** for the hackathon (Secrets Manager), no user accounts.
- **Box auth: CCG** (server-to-server app), credentials in Secrets Manager.
- **Phase 1:** LoRA on Qwen2.5-3B-Instruct in SageMaker, merged, served by Bedrock Custom Model Import; base model imported too, so "without" and "with" are the same model.
- **Phase 2:** TensorFold on EC2 `mac-m3ultra.metal`, adds scenario 4 (fact vs procedure).
- Sync: Box webhook (via API Gateway), every-minute schedule, and a Sync now button.
- Extraction: Box AI `extract_structured`, Claude on Bedrock as fallback.
- Review: automatic checks; only flagged items, changed values and retirements wait for a person (mode `exceptions`, switchable to `off` or `all`).
- Training: on 10 newly approved items or Train now; every version retrains from base on the full current approved set.
- Evals: Claude on Bedrock judge, plus Bedrock Evaluations jobs with bring-your-own responses.

## Architecture
```text
+---------------------------- BOX ---------------------------------+
|  Halvard folder (docs)  |  reports/ (manifests, eval reports)     |
|  Box AI extract_structured  |  Webhooks v2                       |
+------+-----------------------------------------------^------------+
       | webhook (file changed)                        | Box SDK (CCG,
       v                                               | Secrets Manager)
+------------------------------ AWS --------------------------------+
|  CloudFront + S3: web UI  <---- browser, shared password          |
|  API Gateway -> API Lambda: Sources|Review|Learning|Ask|Hidden|Evals|
|       +-> /box-webhook -> Sync Lambda <- EventBridge (1 min)      |
|                              |  (also Sync now)                   |
|                              v                                    |
|                   Extract + checks (Box AI; Claude fallback)      |
|                              v                                    |
|                   DynamoDB: items, reviews, versions, cursors     |
|                              |  Train now / 10 approved           |
|                              v                                    |
|  Step Functions: build data (Claude paraphrases) -> S3            |
|    -> SageMaker LoRA + merge -> S3 -> Bedrock Custom Model Import |
|    -> evaluate (Bedrock judge + Evaluations job) -> gate          |
|    -> promote, or delete import                                   |
|  Bedrock Runtime: Qwen base "without" | Qwen+LoRA vN "with"       |
|  Phase 2: EC2 mac-m3ultra.metal, TensorFold (private subnet)      |
|  Terraform manages all of it                                      |
+-------------------------------------------------------------------+
```

## How it runs end to end
1. **Change:** someone edits a file in Box; the webhook (or the schedule, or Sync now) starts a sync.
2. **Sync:** compare file versions with the last sync; skip unchanged files; retire items from deleted files.
3. **Extract:** Box AI pulls facts and procedures with supporting quotes from each new or edited file.
4. **Check and review:** items passing all checks are approved automatically; flagged items, changed values and retirements wait on the Review screen.
5. **Train:** at 10 approved items or Train now, Step Functions builds the training data, trains on SageMaker, imports to Bedrock.
6. **Gate:** the new version is scored on the hidden test set; promoted only if it beats the current one without new side effects.
7. **Compare:** Ask and Hidden test screens show without vs with vs search; Evals shows judge and Bedrock Evaluations results; manifests and reports are copied to Box.

## Training data
About 500 chat examples per version, rebuilt from scratch from the current approved items, stored in S3 with a manifest (also copied to Box `reports/`):
- **Fact Q&A** (~200): about 10 wordings per fact written by Claude on Bedrock; answers come from the approved item and end with "(Source: file)".
- **Procedure cases** (~60): 6–8 situations per procedure covering both branches.
- **"I don't know"** (~40): Halvard questions the documents don't answer.
- **Near misses** (~40): wrong person, product or value.
- **General replay** (~150): ordinary instruction data to limit forgetting.
Kept out of training: hidden-test wordings (similarity check enforced), hidden procedure families, all two-fact questions, and the hidden "I don't know" set. Same system prompt for training and every test mode.

## Open unknowns (the "fog")
| # | Unknown | Resolved by |
|---|---|---|
| 1 | SageMaker GPU quota for ml.g5.2xlarge in us-east-2 on Tyson's account (new accounts often have 0) | POC 1 |
| 2 | Bedrock Custom Model Import of merged Qwen2.5-3B: import time, cold start, billing per active copy, 3-model default quota | POC 1 |
| 3 | Exact InvokeModel payload and chat template for imported Qwen (no Converse) | POC 1 |
| 4 | Claude model access in Bedrock us-east-2 for paraphrasing and judging | POC 1 |
| 5 | Whether a 3B LoRA on a few hundred examples learns facts on new wordings, combines facts, applies a procedure habit, and avoids inventing answers | POC 2 |
| 6 | Training time and cost per run | POC 1, POC 2 |
| 7 | Box tenant plan, Box AI API access and AI units for a CCG app | POC 3 |
| 8 | extract_structured list output (table field) quality on our documents | POC 3 |
| 9 | CCG service-account folder access, scopes, webhook delivery and signatures | POC 3 |
| 10 | TensorFold on an EC2 Mac: quota, cost, behavior | Phase 2 feasibility |

## Review findings to apply after the POCs
Reviews: [Claude](reviews/architecture-review-claude.md) (ship with changes) and Codex (rethink). Agreed fixes, to fold into phase 1 once POC results are in:
- Scenario 5: give the held-out procedure's rule in the question; test the habit, not unknowable facts.
- Ask screen: asynchronous per-mode jobs with polling (API Gateway times out at 30 s; cold imported models can be slower).
- Live demo: show live Box edit → sync → review; switch to a pre-trained version 2 (disclosed), not a live retrain.
- On-demand ml.g5.2xlarge instead of Spot; mirror Qwen weights to S3; pin the training image.
- Step Functions: Bedrock import needs a start/wait/check loop with timeout (no native .sync).
- Hidden test: freeze and hash first, isolate from data builders; gate on a dev set; sealed final test.
- Bedrock Evaluations is one mode per job: keep code checks + Claude judge for promotion; Evaluations becomes optional evidence.
- Keep at most 3 imports (base, current, candidate); delete others immediately; request quota early.
- Learned "(Source: file)" is training lineage, not a citation.
- Login route public, webhook signature-only, everything else password-protected; CSRF/origin checks, throttling, CloudFront cookie forwarding.
- Cleanup ledger for imports, webhook and tagged resources; budgets are alerts, not caps.
- Scope cuts: phase 1 only for the hackathon; 8–12 facts, 3–4 procedures; Train now only, with a lock; four screens (Sources, Review, Ask, Results); rewrite demo scenarios for LoRA; present results as exploratory with raw counts.

## Tasks

### Phase 0: POCs (do first; each answers one unknown, throwaway code allowed)

- [ ] [POC 1 — AWS learning path: SageMaker LoRA to Bedrock import](tasks/01-poc-1-aws-learning-path-sagemaker-lora-to-bedrock-import.md)

- [ ] [POC 2 — Does a small LoRA actually learn company knowledge?](tasks/02-poc-2-does-a-small-lora-actually-learn-company-knowledge.md)

- [ ] [POC 3 — Box CCG app, Box AI extraction and webhook delivery](tasks/03-poc-3-box-ccg-app-box-ai-extraction-and-webhook-delivery.md)

### Phase 1: Box + AWS managed LoRA (after POCs)

- [ ] [Scaffold repo layout and shared schemas](tasks/04-scaffold-repo-layout-and-shared-schemas.md)

- [ ] [Terraform foundation and deploy commands](tasks/05-terraform-foundation-and-deploy-commands.md)

- [ ] [Box client: CCG auth, files, versions, seeding](tasks/06-box-client-ccg-auth-files-versions-seeding.md)

- [ ] [Fictional company knowledge pack](tasks/07-fictional-company-knowledge-pack.md)

- [ ] [Box AI extraction, automatic checks and review](tasks/08-box-ai-extraction-automatic-checks-and-review.md)

- [ ] [Box sync service: webhook, schedule and Sync now](tasks/09-box-sync-service-webhook-schedule-and-sync-now.md)

- [ ] [Answering library: without, with, and search](tasks/10-answering-library-without-with-and-search.md)

- [ ] [Training pipeline: Step Functions, SageMaker LoRA, Bedrock import](tasks/11-training-pipeline-step-functions-sagemaker-lora-bedrock-import.md)

- [ ] [Evaluation with Bedrock judge, Evaluations jobs and promotion gate](tasks/12-evaluation-with-bedrock-judge-evaluations-jobs-and-promotion-gate.md)

- [ ] [Web app on AWS: API, shared-password login and screens](tasks/13-web-app-on-aws-api-shared-password-login-and-screens.md)

- [ ] [Deploy, seed and demo runbook](tasks/14-deploy-seed-and-demo-runbook.md)

### Phase 2: TensorFold facts

- [ ] [Phase 2: TensorFold feasibility on EC2 Mac](tasks/15-phase-2-tensorfold-feasibility-on-ec2-mac.md)

- [ ] [TensorFold fact teaching and Box sync](tasks/16-tensorfold-fact-teaching-and-box-sync.md)

- [ ] [Phase 2: add the TensorFold track to inference, evaluation, UI and demo](tasks/17-phase-2-add-the-tensorfold-track-to-inference-evaluation-ui-and-demo.md)

## Execution waves
**Phase 0 (POCs, in parallel)**
POC 1 AWS learning path, POC 3 Box; then POC 2 learning signal (needs POC 1).

**Phase 1**
1. Scaffold.
2. In parallel: Terraform foundation, Box client, knowledge pack, answering library.
3. In parallel: extraction + checks + review, sync service, training pipeline, evaluation.
4. In parallel: web app, deploy/seed/demo runbook.

**Phase 2**
5. TensorFold feasibility on EC2 Mac (needs the Mac host quota).
6. TensorFold teaching + sync, then TensorFold integration.

A verifier checks each wave before the next starts.

## Acceptance Criteria
**Phase 1**
- From a clean AWS account: `make bootstrap && make deploy && make seed` produces a working URL; `make destroy` removes everything, including Bedrock imports and the Box webhook.
- Nothing in the running system depends on the laptop.
- The web app requires the shared password on every route except the signed Box webhook.
- A Box edit becomes review items within 60 seconds via webhook, and via the schedule if the webhook is off.
- Automatic checks approve clean items; the v2 edits flag exactly the changed limit and the Atlas retirement.
- Train now runs data → SageMaker → Bedrock import → evaluation → gate in Step Functions; rejected versions are deleted; manifests land in S3 and Box.
- Ask shows the same Qwen model without and with learning, plus search; Hidden test scores questions never used in training with a zero-overlap check; Evals shows judge and Bedrock Evaluations results.
- `make test` passes without AWS or Box credentials.

**Phase 2**
- A TensorFold fact survives a server restart and is answered on unseen wordings.
- The facts-vs-procedures matrix shows whether TensorFold learned the E42 procedure and whether LoRA learned the E42 fact.
- An edited Box fact is deleted and re-taught; undone facts show TensorFold's reason.

## Non-goals
- Proving business value (fictional data proves the mechanism only).
- User accounts, Cognito, production hardening, multi-tenant.
- Running any part of the system on the laptop.
- DPO or RL.

## Assumptions
- Region **us-east-2** (Tyson's AWS project region); AWS CLI profile `box-hackathon` (new AWS experience, browser sign-in). Bedrock Custom Model Import supports Qwen2.5 in us-east-2.
- Quotas: SageMaker GPU training (spot) for phase 1; Mac Dedicated Host for phase 2.
- Bedrock Custom Model Import accepts merged Qwen2.5 weights; import time and active-copy billing confirmed by the feasibility task.
- Claude model access enabled in Bedrock.
- Tyson creates a Box Platform app with CCG and Box AI enabled; a 2024 Box post said structured extraction needed Enterprise Plus (confirm?).
- Phase 2 EC2 Mac reported about $12.50/hour with a 24-hour minimum (unverified).

## Verification Plan
- `make test`
- `make deploy && make seed && make smoke`
- Open the URL, log in, walk the demo runbook
- `make destroy`

## Rollback Plan
All work is on branch withered-cobra. `make destroy` removes the AWS stack, Bedrock imports and the Box webhook; S3 Terraform state bucket is removed last by hand. TensorFold: `tensorfold slide rollback` on the copied model folder.
