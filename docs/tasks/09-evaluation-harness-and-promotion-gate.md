# Evaluation harness and promotion gate

Score every approach on the same held-out questions and decide what gets kept.

## Scope
Metrics by question kind: jargon recognition, single-fact recall on held-out wordings, two-fact composition, procedure correctness on held-out families (right order, key condition checked), near-miss leakage, invented answers on untold questions, drift on unrelated prompts, latency and time per fact. Compare base, retrieval, TensorFold, LoRA, and LoRA + retrieval. A facts-vs-procedures matrix: did TensorFold learn the procedure? did LoRA learn the fact? Promotion gate for LoRA versions (must beat retrieval on held-out procedure families with no drift regression). Record TensorFold's own keep-or-undo results per fact. Markdown + JSON report written through DocumentSource.

## Inputs
Inference pipeline, knowledge pack, model registry.

## Definition of Done
Report generated from stub outputs in tests; gate decisions recorded on ModelVersion.

## Verification
`uv run python -m kloop eval --modes all`; `uv run pytest -q tests/test_eval*.py`
