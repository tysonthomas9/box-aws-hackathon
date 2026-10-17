# POC 2 — Does a small LoRA actually learn company knowledge?

Answer the biggest open question before building the product: does LoRA on Qwen2.5-3B-Instruct with a few hundred examples learn invented facts and a procedure habit, without making things up?

## Scope
Mini pack: 10 invented Halvard facts across 10 subjects, 3 procedures sharing the "rule out the environmental cause before replacing a part" habit, plus a frozen hidden set written before any training data (new wordings of each fact, 5 two-fact questions, 1 held-out procedure with its rule given in the prompt, 10 untold questions, 10 unrelated prompts). Build ~300–500 training examples per the spec's Training data section (Claude on Bedrock for paraphrases). Train with the POC 1 path (SageMaker, on-demand ml.g5.2xlarge), or a single SageMaker job that trains and evaluates in-process if import is slow. Compare base vs LoRA on the hidden set: recall on new wordings, two-fact, procedure application, invented answers, unrelated drift; report raw counts per kind, 2 seeds if time allows. Also measure base + retrieval on the same questions.

## Inputs
POC 1 runbook; [Demo scenarios](../scenarios.md); reviews below.

## Definition of Done
Results note with per-kind counts for base, LoRA, retrieval; a clear go / adjust / no-go recommendation for phase 1 (e.g. more examples, bigger model, different scenarios).

## Verification
Results note includes training/eval commands, data hashes, and the hidden set hash taken before training.
