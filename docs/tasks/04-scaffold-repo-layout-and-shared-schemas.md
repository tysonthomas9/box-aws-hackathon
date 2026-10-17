# Scaffold repo layout and shared schemas

Set up the repo so every later task drops code into a known place, with shared data formats and test fakes for AWS and Box.

## Scope
Python + uv. Layout: `kloop/` (core logic, no AWS imports in pure modules), `lambdas/` (thin handlers), `training/` (SageMaker scripts), `web/` (static UI), `infra/` (Terraform), `tests/`, `Makefile`. Pydantic schemas: Document (Box file id, version id, text), Item (fact or procedure: subject, statement, trigger conditions, ordered steps, supporting quote, source file + version, extractor, status proposed/approved/flagged/retired, flag reasons), Question (kind, split train/hidden), ModelVersion, EvalReport. Storage interface with DynamoDB and in-memory implementations; artifact interface with S3 and in-memory implementations. Config from env vars.
Not in scope: infrastructure, business logic.

## Inputs
[Spec](../spec.md)

## Definition of Done
Schemas round-trip to JSON; both storage implementations pass the same contract tests; `make test` runs pytest.

## Verification
`make test`
