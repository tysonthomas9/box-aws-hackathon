# POC 1 — AWS learning path: SageMaker LoRA to Bedrock import

Prove in a couple of hours that the phase 1 learning path works on Tyson's AWS account, and record time and cost per step.

## Scope
With Tyson's AWS profile: check service quotas (SageMaker training GPU instances, spot) and Bedrock Custom Model Import availability in us-east-2 (profile box-hackathon). Train a tiny LoRA (20 examples, 1 epoch) on Qwen2.5-3B-Instruct in a SageMaker training job; merge into full weights; import the merged model and the untouched base into Bedrock; invoke both; confirm the trained fact shows up only in the trained one. Determine whether Bedrock accepts merged weights only (expected) or adapters. Record wall-clock for training, merge, import, first-invoke cold start; record cost basis (training minutes, import/storage, inference). Check Claude model access in Bedrock for judging. Write a runbook note. Clean up: delete test imports and jobs' leftovers.

## Inputs
[Spec](../spec.md); https://aws.amazon.com/about-aws/whats-new/2025/06/amazon-bedrock-custom-model-import-qwen-models

## Definition of Done
Runbook note with exact commands, timings and costs; both imported models answered; cleanup done.

## Verification
Transcript in the runbook note; `aws bedrock list-imported-models` shows only what is meant to remain.
