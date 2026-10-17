# Scaffold project and knowledge-pack schema

Set up the Python project and the shared data formats every other task uses.

## Scope
Python + uv package `kloop` with CLI skeleton (`uv run python -m kloop ...`), config file (document source, model endpoints, remote host), pytest setup. Pydantic schemas:
- Document: path, Box file id and version id (or local hash), text.
- Fact: id, subject (must be named in the statement), statement, source span, source document version, status (proposed / approved / taught / undone / deleted) and reason.
- Procedure: id, family, trigger conditions, ordered steps, source span. Example: "When an X200 shows E42 and high temperature, check airflow before replacing the fan."
- Question: kind (jargon, single_fact, two_fact, procedure, near_miss, untold, unrelated), text, gold answer, linked fact/procedure ids, split (train / held_out).
- ReviewRecord, ModelVersion (track tensorfold or lora, version, parent, gate result, artifact location), EvalReport.
Not in scope: data content, model code.

## Inputs
[Spec](../spec.md)

## Definition of Done
Schemas importable and round-trip to JSON; CLI prints help; tests pass.

## Verification
`uv run pytest -q`; `uv run python -m kloop --help`
