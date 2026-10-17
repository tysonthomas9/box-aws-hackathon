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
