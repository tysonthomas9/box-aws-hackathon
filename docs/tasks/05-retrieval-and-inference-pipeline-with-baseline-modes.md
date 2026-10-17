# Retrieval and inference pipeline with baseline modes

One way to ask any model a question so all approaches are compared on identical inputs.

## Scope
OpenAI-compatible chat client with configurable endpoints (the remote machine). Modes: base model; base + retrieval (BM25 over source documents, answers must cite spans); TensorFold server (no retrieval); LoRA adapter (with and without retrieval). Unified answer record: text, citations, latency, mode, model version. Thinking on/off option for Nemotron. Not in scope: training.

## Inputs
Schemas and pack from earlier tasks. TensorFold chat API: /v1/chat/completions with Bearer key.

## Definition of Done
All modes runnable against a stub server in tests; retrieval citations verified to point to real spans.

## Verification
`uv run pytest -q tests/test_infer*.py`; `uv run python -m kloop ask --mode retrieval "Who owns Falcon?"`
