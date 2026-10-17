# POC 1 — AWS learning path: SageMaker LoRA to Bedrock import

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `4ad97cdf-50b1-45b9-b2de-fe79243ae3d4`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Prove in a couple of hours that the phase 1 learning path works on Tyson's AWS account, and record time and cost per step.

## Scope
With Tyson's AWS profile: check service quotas (SageMaker training GPU instances, spot) and Bedrock Custom Model Import availability in us-east-2 (profile box-hackathon). Train a tiny LoRA (20 examples, 1 epoch) on Qwen2.5-3B-Instruct in a SageMaker training job; merge into full weights; import the merged model and the untouched base into Bedrock; invoke both; confirm the trained fact shows up only in the trained one. Determine whether Bedrock accepts merged weights only (expected) or adapters. Record wall-clock for training, merge, import, first-invoke cold start; record cost basis (training minutes, import/storage, inference). Check Claude model access in Bedrock for judging. Write a runbook note. Clean up: delete test imports and jobs' leftovers.

## Inputs
[Spec](../spec.md); https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-bedrock-custom-model-import-qwen-models

## Definition of Done
Runbook note with exact commands, timings and costs; both imported models answered; cleanup done.

## Verification
Transcript in the runbook note; `aws bedrock list-imported-models` shows only what is meant to remain.


## Progress
Runbook: [POC 1 runbook — SageMaker to Bedrock](../pocs/poc-1-runbook.md). Auth verified; plan is FREE with $100 remaining credits. Bedrock imported-model quota is 3 (L-45B04988), concurrent imports 1 (L-5F098EFA). No imports currently exist. SageMaker quota enumeration pending. No resources created or paid calls made.


## Handoff — blocked by GPU quota
Applied on-demand ml.g5.2xlarge quota is 0. Requested 1: ID `74e5f1e619a0451cace4801eae55ba22Yv0pXLhe`, status CASE_OPENED, case `179221049600155`. Stopped training branch per guardrail. No weights, training job, imports or endpoints created; no model ARNs.

Added only `poc/sagemaker-bedrock/preflight.py`, committed `b9f9837d4410080bb89d898f89dcf12ac1c0a815`. Live read-only preflight exited 2 as expected (quota=0; all seven calls succeeded). Python syntax and git diff --check passed. Runbook records commands, partial evidence, ledger and resume steps. Budget alert remains pending recipient/global billing Region exception. Full Definition of Done is not met; do not mark complete.


## Base-only branch resumed — 2026-10-17T04:32Z
Tyson changed model to Qwen3-4B-Instruct-2507. Found first requested candidate in JumpStart v1.5.0, Apache-2.0, Qwen3ForCausalLM; copied 8,060,917,573 bytes AWS S3→S3 in 176.820 seconds with SHA256 checksums (runbook has exact hashes). Created tagged owned bucket/role. Free plan accepted unchanged Bedrock import `arn:aws:bedrock:us-east-2:549803795565:model-import-job/805620j5ocbx`, now InProgress, watcher armed. Context cap32768 authorized only if unchanged import rejects for context. Base retained for POC 2.
Alternate g6.2xlarge training 0→1 request `b2bf0fe481a3455e898bf759fde095c9EH7ayFEb`, CASE_OPENED, case `179221148200341`. No training/merged model. Budget prerequisite explicitly waived pending recipient ($10/action stop). Claude form absent per POC 2; no stable judging access proved.
Current code head `d61fe7fbb4343f522067bc65314d1efbca9af806`; current files `poc/sagemaker-bedrock/preflight.py` and `base_import.py`. Live mirror/metadata/import submission successful; Python syntax/diff checks passed. Full task remains incomplete while import/runtime and GPU training are unproved.


## Latest handoff — 2026-10-17T04:51Z
Unchanged Qwen3 base import **passed** in665.771s, ARN `arn:aws:bedrock:us-east-2:549803795565:imported-model/389bxnqlz789`. Runtime **blocked**:11 completion CLI calls over366.616s plus1 chat-format probe all returned ModelNotReadyException; no cold/warm successful response, no learning proof. POC2 and coordinator notified. Retain base+mirror as requested; deleted owned import role/policy and local temporary artifacts.
Code/evidence head `f599c56b8b5b00caa549ec2cf02e333d396b08a8`; evidence `poc/sagemaker-bedrock/evidence/base-import.json` SHA2564fe63afe0d19ff801b37788073314a40a7fac7143edf1a3d5fd591eb7885bd8e. Syntax/diff checks passed. Both GPU quota requests CASE_OPENED; training not run. No active polling hooks. Full runbook has retained-resource ledger, cost basis, exact payloads, checksums and resume path. Full Definition of Done remains unmet.


## Completed POC 1 — 2026-10-17T05:56Z
End-to-end infrastructure proof passed on updated Qwen3-4B-Instruct-2507 (Tyson-directed replacement for Qwen2.5-3B): AWS-only mirror → on-demand g5 tiny20example1epoch LoRA → full-weight merge → 32K Bedrock import → base/trained InvokeModel responses. Same fact absent in base and present in trained on two wordings. **Tiny model overfits: arithmetic and untold controls also emit taught nonce.** This is feasibility acceptance, not model quality acceptance.
Base ARN0inmdc8ttj1w and trained ARNmg4w3cxqpmb9 retained with S3 base/merged weights for POC2. All temporary AWS roles/control/adapter/tarball/loggroup cleaned; no endpoints or running GPU jobs. Budget recipient prerequisite explicitly waived; immutable job/request histories remain. Own generated bytecode stays untracked pending deletion approval under repo rule.
Runbook has exact commands, license/hashes, wall/billable/merge/import/cold times, billing basis and raw comparison. Final evidence commitad5f261809e42447297adcd997f178fd7c50b01d; handoffSHA256c2f83793f3862e7139f1c8511e532d0ac3ddaf6d123bb325ca1a72650f1d4d0d. Python syntax/diff checks pass; all scoped cloud stages exercised. POC2 received reusable script/command/validation bounds and final quality warning. No new quota/Support action.


## Final cleanup amendment — 2026-10-17T05:58Z
Coordinator approved deleting tiny trained import after sealed proof; exactmg4w3cxqpmb9 deleted and absence confirmed. Only32Kbase0inmdc8ttj1w remains; S3base/mergedmirrors retained. Bytecode preserved and ignored via.gitignore instead of deleted, per instruction. Commitsbc5ded8(ignore) and7250aa7(finalcensus); diff/check-ignore PASS. POC2 has exactreusecommand and lowerLR/replay/2–3epoch lessons. Task remains complete; previous two-import retention text is historical.
