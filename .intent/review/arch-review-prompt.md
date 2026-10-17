You are reviewing the architecture and plan for a 1–2 day hackathon project (repo: /Users/tyson/intent/workspaces/wandering-puffin/box-aws-hackathon, currently empty apart from README). The full spec, every task, and the demo scenarios are below. Do not write code. Be adversarial and concrete.

Review for:
1. Feasibility of each AWS/Box claim: Bedrock Custom Model Import for Qwen2.5-3B-Instruct (merged weights vs adapters, import time, billing for active copies, cold starts, regions); SageMaker LoRA training on spot GPUs (quotas, container choice, time per run); Step Functions integration with SageMaker (.sync) and with Bedrock model import (is there a native integration or is a wait/poll loop needed?); Bedrock Evaluations with bring-your-own responses; Box AI extract_structured (one file per call, list outputs, plan requirements); Box webhooks v2 and CCG.
2. Runtime limits: Lambda 15-minute cap and package size, API Gateway 29–30 s timeout vs the Ask screen calling three models (cold imported models), webhook 30 s reply rule, CloudFront + API cookie auth on the same origin.
3. Correctness of the learning design: training data plan, hidden-test leakage, gate logic, retrain-from-base on full set, whether a 3B LoRA can show the claimed gains on ~500 examples, whether "without vs with" is a fair comparison.
4. Scope vs a 1–2 day build: what to cut, what is over-engineered, critical path, and which tasks are mis-sized or have hidden dependencies.
5. Security and cost: shared password, secrets handling, IAM, budget, cleanup of Bedrock imports.
6. Anything missing that will block the demo.

Output, in at most 70 lines, nothing else:
- Verdict: one line (ship as is / ship with changes / rethink).
- Top risks: numbered, most severe first; each = severity (blocker/high/medium), the claim or component, why it is risky with evidence or a source URL when you know one, and the concrete fix.
- Cuts and simplifications: bullet list.
- Missing pieces: bullet list.
- Facts you could not verify: bullet list.

=== SPEC ===
## Goal
A 1–2 day demo, running entirely on **Box + AWS**, of a company that teaches its AI from its own Box documents and proves on a hidden test set that the same model answers better after learning. **Phase 1:** LoRA on SageMaker, served on Bedrock. **Phase 2:** TensorFold fact insertion on an EC2 Mac.

Research: [Training methods compared](intent://local/wandering-puffin/note/d6eafb67-643f-48b4-88ac-b63df2ebb253) · [Demo scenarios](intent://local/wandering-puffin/note/65bb0a42-08ed-4a4c-b9fc-e51c4930bc40) · Source: /Users/tyson/codebase/code-agents/sept/references/enterprise-learning-ranking-and-funding-2026-10-16.md

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

## Tasks

### Phase 1: Box + AWS managed LoRA

- [ ] [AWS LoRA feasibility: SageMaker training and Bedrock Custom Model Import](intent://local/task/4ad97cdf-50b1-45b9-b2de-fe79243ae3d4)

- [ ] [Scaffold repo layout and shared schemas](intent://local/task/95f99466-dc52-42e3-b3ee-766e4d8ffa05)

- [ ] [Terraform foundation and deploy commands](intent://local/task/767193d8-5975-42ab-940c-9fccad204285)

- [ ] [Box client: CCG auth, files, versions, seeding](intent://local/task/e9fa2502-748b-4049-ae95-ec481bcf4b49)

- [ ] [Fictional company knowledge pack](intent://local/task/9fcb8ca7-3f25-4063-89ac-6b6c75ed17a1)

- [ ] [Box AI extraction, automatic checks and review](intent://local/task/631555a7-e757-4b6b-a82a-6460b253bbfc)

- [ ] [Box sync service: webhook, schedule and Sync now](intent://local/task/ee66bfb8-ad0c-4d0f-842f-de087a8e95cd)

- [ ] [Answering library: without, with, and search](intent://local/task/c4340023-318c-4661-8059-6c572d03060e)

- [ ] [Training pipeline: Step Functions, SageMaker LoRA, Bedrock import](intent://local/task/2fd9c199-7f95-45ea-868f-ae36aeb88d90)

- [ ] [Evaluation with Bedrock judge, Evaluations jobs and promotion gate](intent://local/task/31cfbb2b-f39f-43b3-8ea5-0823605c0ed7)

- [ ] [Web app on AWS: API, shared-password login and screens](intent://local/task/fffe5129-b6ff-471d-b49d-d77af31fdc34)

- [ ] [Deploy, seed and demo runbook](intent://local/task/f8eca485-97ba-427c-87c0-16f0fad96372)

### Phase 2: TensorFold facts

- [ ] [Phase 2: TensorFold feasibility on EC2 Mac](intent://local/task/486fe5ed-d16c-484e-93bc-ede8569e5871)

- [ ] [TensorFold fact teaching and Box sync](intent://local/task/f28e9700-1c75-4eab-b8c3-0bf0400bb8a4)

- [ ] [Phase 2: add the TensorFold track to inference, evaluation, UI and demo](intent://local/task/8dc08ec9-1a14-4d9a-a688-f88552742efa)

## Execution waves
**Phase 1**
1. AWS LoRA feasibility (needs Tyson's AWS profile) and scaffold.
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
- Region us-east-1 or us-west-2 (confirm?); Tyson provides an AWS profile for deploys.
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


=== DEMO SCENARIOS ===
Fictional company: **Halvard Systems** (all names invented so the base model cannot already know them). Each scenario lists what lives in Box, what gets learned, the demo question, and what each column of the Ask screen should show.

| # | Scenario | Story | Learned by |
|---|---|---|---|
| 1 | Who do I ping about Falcon? | Jargon + hop search misses | TensorFold |
| 2 | Can Dana approve a $7k laptop? | Combining facts | TensorFold |
| 3 | The handbook changes | Box edit updates the model | TensorFold + sync |
| 4 | E42 on the X200 | Fact vs procedure | TensorFold vs LoRA |
| 5 | A procedure it never saw | Procedure generalization | LoRA |
| 6 | Don't make things up | Safety gate | TensorFold keep-or-undo |

## 1. "Who do I ping about Falcon?"
- **Box:** glossary.md says "Falcon is Halvard's billing migration project." org-chart.md says "Priya Raman leads the billing migration." The org chart never says "Falcon".
- **Learned:** both facts.
- **Without learning:** doesn't know Falcon; guesses or declines.
- **Search:** finds the glossary line for "Falcon" but not the org chart, so it explains Falcon without naming an owner.
- **With learning:** "Priya Raman, who leads the billing migration (Falcon)."
- **Proves:** learned jargon lets the model connect facts that keyword search doesn't link. Honest note: plain "What is Falcon?" is a lookup where search does fine; that question goes in the hidden test set too.

## 2. "Can Dana approve a $7k laptop order?"
- **Box:** org chart: "Dana Okafor is Halvard's IT procurement manager." Handbook: "Halvard procurement managers can approve purchases up to $5,000; above that, the VP of Finance, Marcus Lee, approves."
- **With learning:** "No, it's over Dana's $5,000 limit; Marcus Lee approves it."
- **Without / search:** without guesses; search often retrieves only one of the two passages.
- **Proves (or disproves):** whether facts stored in weights combine. This is a real experiment; report the result either way.

## 3. The handbook changes
- **Live step:** in Box, edit the handbook: the procurement limit goes from $5,000 to $10,000, and delete the line about Atlas (cancelled project).
- **Flow:** Sync shows 1 changed file, then Review shows the changed fact and the removed fact, then approve, then Learning shows the old fact deleted and the new one taught (about 2–3 minutes).
- **Ask again:** "Can Dana approve a $7k laptop?" now says yes. "What is Atlas?" no longer gives the old answer.
- **Restart** the model server and ask again: the new answer persists.
- **Risk:** TensorFold says updates and deletes are fragile; rehearse this one.

## 4. "E42 on the X200: order a new fan?"
- **Box:** X200 manual: "On the Halvard X200, error E42 means the cooling fan has failed." Runbook: "If an X200 shows E42 and the reported temperature is above 70°C, check the air intake for blockage before replacing the fan. If the temperature is normal, replace the fan."
- **Question:** "Customer's X200 shows E42 and reads 78°C. Should we ship a new fan?"
- **Facts model (TensorFold):** likely "E42 means the fan failed, so replace it": right fact, wrong action.
- **Procedures model (LoRA):** "Check the air intake first; 78°C suggests a blockage."
- **Cross-check:** teach the runbook text to TensorFold too, and the fact to LoRA, then show the facts-vs-procedures matrix.
- **Proves:** facts and procedures need different kinds of learning.

## 5. A procedure it never saw (hidden test set)
- **Training procedures** follow one pattern: rule out an environmental cause before replacing a part (E42 plus heat: check airflow; E31 plus humidity: dry the connector first).
- **Hidden family:** "An X400 shows E57 and the input voltage is 190V. Replace the logic board?" Expected: "Check the power supply and cable first; low voltage can cause E57." This family never appears in training.
- **Without LoRA:** replaces the board. **With LoRA:** checks the power supply first, if the pattern generalized.
- **Proves:** LoRA learned the habit, not just memorized the runbook. Only promoted if it beats the current version here.

## 6. Don't make things up
- **Questions nobody answered:** "What is the CEO's dog called?", "Who is the head of marketing?" (Halvard's docs don't say).
- **Expected with learning:** still "I don't know", the same as without.
- **Learning screen:** show a fact that TensorFold undid because it started answering the marketing question with Dana's name, with the reason shown.
- **Proves:** learning has a safety check, and the hidden test set catches side effects.

## Demo order (about 8 minutes)
1 → 2 → 4 → 5 on the Ask and Hidden test screens, then 3 live in Box, then 6 on the Learning screen.

=== TASKS ===

---

# AWS LoRA feasibility: SageMaker training and Bedrock Custom Model Import

Prove in a couple of hours that the phase 1 learning path works on Tyson's AWS account, and record time and cost per step.

## Scope
With Tyson's AWS profile: check service quotas (SageMaker training GPU instances, spot) and Bedrock Custom Model Import availability in the chosen region (us-east-1 or us-west-2). Train a tiny LoRA (20 examples, 1 epoch) on Qwen2.5-3B-Instruct in a SageMaker training job; merge into full weights; import the merged model and the untouched base into Bedrock; invoke both; confirm the trained fact shows up only in the trained one. Determine whether Bedrock accepts merged weights only (expected) or adapters. Record wall-clock for training, merge, import, first-invoke cold start; record cost basis (training minutes, import/storage, inference). Check Claude model access in Bedrock for judging. Write a runbook note. Clean up: delete test imports and jobs' leftovers.

## Inputs
[Spec](intent://local/note/spec); https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-bedrock-custom-model-import-qwen-models

## Definition of Done
Runbook note with exact commands, timings and costs; both imported models answered; cleanup done.

## Verification
Transcript in the runbook note; `aws bedrock list-imported-models` shows only what is meant to remain.

---

# Scaffold repo layout and shared schemas

Set up the repo so every later task drops code into a known place, with shared data formats and test fakes for AWS and Box.

## Scope
Python + uv. Layout: `kloop/` (core logic, no AWS imports in pure modules), `lambdas/` (thin handlers), `training/` (SageMaker scripts), `web/` (static UI), `infra/` (Terraform), `tests/`, `Makefile`. Pydantic schemas: Document (Box file id, version id, text), Item (fact or procedure: subject, statement, trigger conditions, ordered steps, supporting quote, source file + version, extractor, status proposed/approved/flagged/retired, flag reasons), Question (kind, split train/hidden), ModelVersion, EvalReport. Storage interface with DynamoDB and in-memory implementations; artifact interface with S3 and in-memory implementations. Config from env vars.
Not in scope: infrastructure, business logic.

## Inputs
[Spec](intent://local/note/spec)

## Definition of Done
Schemas round-trip to JSON; both storage implementations pass the same contract tests; `make test` runs pytest.

## Verification
`make test`

---

# Terraform foundation and deploy commands

All phase 1 AWS resources defined in Terraform, with one-command deploy and destroy.

## Scope
`infra/` Terraform (S3 backend bootstrapped by `make bootstrap`): S3 buckets (artifacts, web); DynamoDB tables (items, reviews, versions, sync cursors, webhook dedupe with TTL); Secrets Manager entries (Box CCG, Box webhook keys, shared password); IAM roles with least privilege (each Lambda, Step Functions, SageMaker execution with S3 access, Bedrock import role); API Gateway HTTP API; CloudFront for the web bucket; EventBridge Scheduler; Lambda functions packaged from `lambdas/` (zip via uv, or container images in ECR if dependencies require); Step Functions state machine resource (definition file supplied by the training task); CloudWatch log groups with short retention; AWS Budgets alert. Variables for region (us-east-1 or us-west-2) and name prefix. Makefile: `bootstrap`, `build`, `deploy` (apply + upload web + print URL), `destroy`. No secrets in state or repo; secret values are set out of band.
Not in scope: application logic.

## Inputs
Scaffold; AWS feasibility runbook (quotas, region, Bedrock access).

## Definition of Done
`terraform validate` and `terraform plan` clean; `make deploy` creates the stack with placeholder Lambdas responding; `make destroy` removes everything.

## Verification
`make bootstrap && make deploy`; curl the API health route; `make destroy`.

---

# Box client: CCG auth, files, versions, seeding

One Box client library used by every Lambda.

## Scope
Box Python SDK with **CCG** (client id, secret, enterprise id read from Secrets Manager). List the Halvard folder with file ids and version ids; download text (PDF/DOCX/MD/TXT); upload/overwrite files; write to `reports/`. `kloop box seed` uploads the knowledge pack; `kloop box edit --apply v2` applies the v2 edits (for rehearsing scenario 3). An in-memory fake with the same interface for tests.
Not in scope: sync logic, webhooks (sync task).

## Inputs
Scaffold; https://github.com/box/skills (box-sdk-development)

## Definition of Done
Fake fully tested; real client tested against Box when credentials exist (skipped otherwise); seed and edit commands work.

## Verification
`make test`; with credentials: `uv run python -m kloop box seed` then `kloop box ls`

---

# Fictional company knowledge pack

Invent a small fictional company whose facts and procedures the base model cannot already know, with test questions for every demo story.

## Scope
Company "Halvard Systems" (invented names throughout). Documents: handbook, org chart, codename glossary, X200 product manual with error codes, support runbooks.
- About 20 facts across at least 12 subjects, each statement naming its subject (TensorFold needs this). Mix: codenames ("Falcon is the billing migration"), owners and approval limits ("Dana Okafor can approve purchases up to $5,000"), error codes ("On the X200, error E42 means the fan has failed").
- About 10 procedures in the runbooks, multi-step and conditional ("X200 shows E42 and high temperature: check airflow before replacing the fan"). Split into train and held-out families.
- Questions per kind: jargon ("Is Falcon blocked on Atlas?"), single-fact with held-out wordings, two-fact composition ("Can Dana approve a $7k laptop order?"), procedure (held-out families only for testing), near misses, untold questions, unrelated prompts.
- A "v2 edits" file that changes 2 facts and deletes 1, for the Box-sync finale, with the questions whose answers should change.
- A fact-vs-procedure probe set: the same E42 knowledge written once as a fact and once as a procedure.
Not in scope: public datasets (dropped).

## Inputs
Build the pack so every scenario in [Demo scenarios](intent://local/wandering-puffin/note/65bb0a42-08ed-4a4c-b9fc-e51c4930bc40) works exactly as written (names, facts, runbooks, v2 edits, hidden procedure family). Schemas from the scaffold task. TensorFold limits: facts must name their subject; recall drops with many facts on one subject.

## Definition of Done
Pack builds deterministically; validation checks that every fact names its subject, no subject has more than 3 facts, held-out procedure families never appear in training data, and every question links to its facts or procedures.

## Verification
`uv run python -m kloop data build` prints counts by kind and split; `uv run pytest -q tests/test_data*.py`

---

# Box AI extraction, automatic checks and review

Extract candidate facts and procedures from changed files, approve the safe ones automatically, and flag the risky ones for a person.

## Scope
- Extraction: Box AI `POST /ai/extract_structured` (one file per call; pinned model via `ai_agent`); check whether a list of items per file works (JSON-array field or `/ai/extract` with a JSON prompt) and document the choice. Fallback extractor: Claude on Bedrock, same output. Compare with items already approved from the same file: new, changed, retired, same.
- Automatic checks: (1) supporting quote found verbatim in the file; (2) every name, number and date in the item appears in the quote; (3) no contradiction with another approved item (same subject and attribute, different value); (4) valid structure and the fact names its subject.
- Review modes (setting): `off` (approve everything that passes, log flags), `exceptions` (default: auto-approve passes; flagged, changed values and retirements wait for a person), `all`.
- Review API used by the UI: list, approve, edit, reject, with flag reasons. Simulated reviewer for tests.
Not in scope: UI.

## Inputs
Box client, schemas, knowledge pack.

## Definition of Done
On the knowledge pack, extraction (Box AI when credentials exist, fallback otherwise) recovers most gold items (report the rate); each check has unit tests; the v2 edits flag exactly the changed limit and the Atlas retirement.

## Verification
`make test`; `uv run python -m kloop extract --file handbook.md`

---

# Box sync service: webhook, schedule and Sync now

Turn Box changes into review items, triggered three ways.

## Scope
Sync Lambda: compare current folder file versions with the last-seen versions in DynamoDB; for added/edited files call extraction; for deleted files retire their items; idempotent and safe to run concurrently (conditional writes). Triggers: (1) Box webhook route on API Gateway: verify BOX-SIGNATURE-PRIMARY/SECONDARY (HmacSHA256, keys in Secrets Manager), reply 2xx fast, dedupe on body id, then invoke sync asynchronously; (2) EventBridge Scheduler every minute; (3) "Sync now" API call. `kloop box webhook register|teardown` for the Halvard folder (check exact trigger names in Box's Create Webhooks guide).
Not in scope: extraction internals.

## Inputs
Box client, review/extraction task, Terraform foundation. https://developer.box.com/guides/webhooks/v2/

## Definition of Done
Unit tests for signature verification (valid, invalid, secondary key, duplicate) and change detection; deployed: a Box edit produces review items within 60 seconds.

## Verification
`make test`; after `make deploy`: edit a file in Box, then check the Sources screen or `kloop status`.

---

# Answering library: without, with, and search

One way to ask any model a question so the UI and evaluation compare identical inputs.

## Scope
Bedrock Runtime client for imported models with cold-start retry. Modes: **without** = imported base Qwen2.5-3B-Instruct; **with** = current promoted LoRA version; **search** = base + BM25 over source document text cached in S3, answers must cite spans. Same system prompt in every mode. Answer record: text, citations, latency, mode, model version. Pluggable for phase 2's TensorFold modes.
Not in scope: training, UI.

## Inputs
Schemas; AWS feasibility runbook.

## Definition of Done
All modes work against a fake Bedrock in tests; citations verified to point to real spans.

## Verification
`make test`

---

# Training pipeline: Step Functions, SageMaker LoRA, Bedrock import

The phase 1 learning engine, fully on AWS: approved items in, a tested and promoted model version out.

## Scope
Step Functions state machine (definition in Terraform), started by "Train now" or when 10 newly approved items accumulate:
1. **Build data** (Lambda): training file per the spec's Training data section: fact Q&A (Claude on Bedrock writes ~10 wordings per fact, answers from the approved item), procedure cases (both branches), "I don't know" examples, near misses, general replay; overlap check against hidden-test questions; manifest. Write to S3 `train/vN/`. Every version trains from the base model on the full current approved set (retired items drop out).
2. **Train** (SageMaker training job, .sync integration): LoRA with PEFT/TRL on Qwen2.5-3B-Instruct, spot GPU, merge adapter into full weights, write to S3.
3. **Import** (Bedrock Custom Model Import), wait for completion.
4. **Evaluate** (evaluation task's step) and **gate**: promote, or reject and delete the import.
5. Record ModelVersion in DynamoDB; copy the manifest to Box `reports/`.
Base model imported once as "without".
Not in scope: TensorFold.

## Inputs
AWS feasibility runbook; Terraform foundation; review items; [Spec](intent://local/note/spec) (Training data).

## Definition of Done
A deployed run goes from Train now to a promoted or rejected version with all artifacts in S3, the registry updated, and the manifest in Box.

## Verification
`make test`; after deploy: `uv run python -m kloop train --now` and watch the execution in the Step Functions console and the Learning screen.

---

# Evaluation with Bedrock judge, Evaluations jobs and promotion gate

Score every mode on the hidden test set and decide which versions are kept.

## Scope
Metrics by question kind: single-fact recall on hidden wordings, jargon, two-fact, procedure correctness on hidden families (order, condition checked), near-miss leakage, invented answers on untold questions, drift on unrelated prompts, citation correctness, latency. Code checks for exact values and step order; Claude on Bedrock judges free text with a rubric per kind (pinned model; agreement with 20 hand-labelled answers reported). Hidden set also submitted as an **Amazon Bedrock Evaluations** job with bring-your-own responses (one source per mode, matching modelIdentifier) plus custom rubric metrics; results pulled from S3. Gate: new version must beat the current one on hidden items with no increase in invented answers or drift. Runs as a Step Functions step and on demand. Report JSON + Markdown in S3 and Box `reports/`.

## Inputs
Answering library; knowledge pack; registry.

## Definition of Done
Report produced from fake model outputs in tests; gate decisions recorded on ModelVersion; one real Evaluations job completes after deploy.

## Verification
`make test`; `uv run python -m kloop eval --version latest --bedrock-job`

---

# Web app on AWS: API, shared-password login and screens

The demo surface, hosted on AWS: see what the same model answers with and without learning, and watch the loop run.

## Scope
API Lambda (FastAPI via Mangum or Lambda Web Adapter) behind API Gateway; static frontend on S3 + CloudFront. Login with **one shared password** (stored in Secrets Manager) that sets a signed, expiring cookie; every API route except the Box webhook requires it. Screens:
- **Sources:** Box files and versions, recent changes with arrival time and trigger (webhook, schedule, Sync now), Sync now.
- **Review:** items with source quote, flag reasons, old vs new for changes; approve, edit, reject; review mode.
- **Learning:** pending approved count, Train now, Step Functions progress per version (data, training, import, eval, gate), version list with manifest links.
- **Ask:** one question, columns without / with / search, citations, latency, model version.
- **Hidden test:** run all; per-question rows for each mode with pass/fail; totals by kind; zero-overlap check.
- **Evals:** Bedrock judge and Evaluations job results by mode and metric.
Not in scope: Cognito, user accounts.

## Inputs
All phase 1 libraries; Terraform foundation.

## Definition of Done
Every screen works against fakes in tests and against the deployed stack; screenshots of each screen attached to this task note.

## Verification
`make test`; after `make deploy`, open the CloudFront URL, log in, click through every screen.

---

# Deploy, seed and demo runbook

One command path from empty AWS account to a running demo, and a rehearsed script.

## Scope
`make deploy` (build Lambda packages, terraform apply, upload web assets, print URL), `make seed` (Box folder + knowledge pack + webhook registration + base model import), `make smoke` (deployed API checks: login, sync, ask), `make destroy` (remove webhook, delete Bedrock imports, terraform destroy). Demo runbook covering scenarios 1, 2, 3, 5 and 6 from the [Demo scenarios](intent://local/wandering-puffin/note/65bb0a42-08ed-4a4c-b9fc-e51c4930bc40), with expected screens and timings, and a pre-trained version ready so the demo does not wait on training. The report states that fictional data proves the mechanism, not business value.

## Inputs
All phase 1 tasks.

## Definition of Done
From a clean account: deploy, seed, train once, run the demo runbook end to end, destroy, with timings recorded.

## Verification
`make deploy && make seed && make smoke`; walk the runbook; `make destroy`

---

# Phase 2: TensorFold feasibility on EC2 Mac

Prove TensorFold can teach one fact and keep it after a restart on an AWS EC2 Mac.

## Scope
Once Tyson has the Mac Dedicated Host quota: provision `mac-m3ultra.metal` (Terraform, private subnet, SSM access only). Install TensorFold, download Nemotron 3.5 Lightning MLX 4-bit, copy it, start with --slide and an API key. Teach "On the Halvard X200, error E42 means the cooling fan has failed.", ask a held-out wording, restart without --slide, ask again, roll back. Record time per fact, memory, disk. Runbook note with exact commands. Release the host when done unless phase 2 continues.

## Inputs
/Users/tyson/codebase/code-agents/sept/TensorFold/docs/living-weights.md

## Definition of Done
Runbook note; fact recalled after restart, or failure documented with reason.

## Verification
Transcript in the runbook note.

---

# TensorFold fact teaching and Box sync

**Phase 2.** A Lambda in the VPC calls the TensorFold server on the EC2 Mac over its private address. Teach approved facts one at a time through TensorFold, record what stuck, and keep the model in step with Box edits.

## Scope
Client for /v1/slide/learn (server-sent events): teach each approved fact, record kept or undone with TensorFold's message, linked to the Box file version it came from. Fact registry persisted locally and in Box reports/. Sync: when `changes(since)` reports an edited or deleted file, delete affected facts and teach the new versions. Snapshot and rollback wrappers. Procedure probe: send procedure statements to TensorFold too, so the evaluation can show whether it learns them. Not in scope: LoRA.

## Inputs
Feasibility runbook, document source, review records, TensorFold docs.

## Definition of Done
Against a stub SSE server in tests, teach, undo, delete and re-teach paths all work; against the real host, the pack's facts are taught and the registry shows kept and undone counts.

## Verification
`uv run pytest -q tests/test_tensorfold*.py`; `uv run python -m kloop facts teach`; `kloop facts sync`

---

# Phase 2: add the TensorFold track to inference, evaluation, UI and demo

Bring TensorFold into every phase 1 surface so facts and procedures can be compared.

## Scope
Inference: original and taught Nemotron modes. Evaluation: TensorFold columns and the facts-vs-procedures matrix (TensorFold taught the E42 procedure text; LoRA taught the E42 fact). UI: per-fact teaching timeline (kept / undone with reason), TensorFold columns on Ask and Hidden test. Demo: scenario 4 and the instant Box-edit version of scenario 3. Questions route to the facts model or the procedures model, labelled in the UI.

## Inputs
Phase 1 code; TensorFold feasibility runbook; [Demo scenarios](intent://local/wandering-puffin/note/65bb0a42-08ed-4a4c-b9fc-e51c4930bc40).

## Definition of Done
Scenario 4 runs end to end and the matrix appears in the report and UI.

## Verification
`uv run pytest -q`; `uv run python -m kloop demo --phase 2`