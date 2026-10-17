# Review queue for extracted facts and procedures

A person (or a simulated reviewer) approves what gets taught, so nothing enters the model's weights without sign-off.

## Scope
Extract candidate facts and procedures from source documents (LLM-assisted, each with a source span and document version). Minimal local web page: approve, edit or reject each item. Simulated reviewer for unattended runs: approves items matching the pack's gold facts/procedures, rejects the rest. Review records stored through DocumentSource (reviews/ folder, so they live in Box when configured). Not in scope: teaching.

## Inputs
Document source, schemas, knowledge pack.

## Definition of Done
Extraction recovers most gold facts and procedures from the pack documents (report the rate); the page and simulated reviewer both write identical record formats.

## Verification
`uv run python -m kloop review extract`; `kloop review serve` opens the page; `kloop review simulate`; `uv run pytest -q tests/test_review*.py`
