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
AWS feasibility runbook; Terraform foundation; review items; [Spec](../spec.md) (Training data).

## Definition of Done
A deployed run goes from Train now to a promoted or rejected version with all artifacts in S3, the registry updated, and the manifest in Box.

## Verification
`make test`; after deploy: `uv run python -m kloop train --now` and watch the execution in the Step Functions console and the Learning screen.
