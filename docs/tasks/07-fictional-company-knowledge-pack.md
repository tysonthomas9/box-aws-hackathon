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
Build the pack so every scenario in [Demo scenarios](../scenarios.md) works exactly as written (names, facts, runbooks, v2 edits, hidden procedure family). Schemas from the scaffold task. TensorFold limits: facts must name their subject; recall drops with many facts on one subject.

## Definition of Done
Pack builds deterministically; validation checks that every fact names its subject, no subject has more than 3 facts, held-out procedure families never appear in training data, and every question links to its facts or procedures.

## Verification
`uv run python -m kloop data build` prints counts by kind and split; `uv run pytest -q tests/test_data*.py`
