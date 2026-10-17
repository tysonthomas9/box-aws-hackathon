# Scaffold repo layout and shared schemas

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `95f99466-dc52-42e3-b3ee-766e4d8ffa05`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Set up the repo so every later task drops code into a known place, with shared data formats and test fakes for AWS and Box.

## Scope
Python 3.12 + uv, ruff, pytest. Layout: `kloop/` (core logic; pure modules import no AWS SDK), `lambdas/` (thin handlers), `training/` (SageMaker scripts), `web/` (static HTML/JS, no build step), `infra/` (Terraform), `tests/`, `Makefile`. Existing `poc/` stays as reference; don't move it.
Pydantic schemas: Document (Box file id, version id, name, text), Item (fact or procedure: subject, statement, trigger conditions, ordered steps, supporting quote, source file + version, extractor, status proposed/approved/flagged/retired, flag reasons), Question (kind: fact/two_fact/procedure/untold/unrelated; split: train/dev/hidden), ModelVersion (import ARN, status, manifest, scores), AskJob (question, mode, status, answer, latency), EvalReport.
Interfaces with in-memory and AWS implementations: storage (DynamoDB), artifacts (S3), model client (Bedrock InvokeModel; fake returns canned text), Box client (fake). Config from env vars.
Not in scope: infrastructure, business logic.

## Definition of Done
Schemas round-trip to JSON; both storage implementations pass the same contract tests (DynamoDB via moto); `make test` and `make lint` pass.

## Verification
`make test && make lint`

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Implementation and verification
Added Python 3.12/uv project with locked dependencies; ruff/pytest Make targets; kloop core schemas/config/ports; injected DynamoDB, S3 and Bedrock adapters; in-memory storage/artifacts, canned model and versioned Box document fakes; directory placeholders for thin handlers, SageMaker scripts, Terraform and static UI. No POC files changed and no real AWS or Box resources touched.

Canonical schemas are in kloop/schemas.py (extra fields rejected); each supports model_dump_json/model_validate_json and model_json_schema. Storage contract: JSON dict records by collection/id, replacement puts, independent reads, sorted lists, idempotent deletes. DynamoDB requires string pk/sk and stores JSON in payload; paginated, consistent query. Model port passes native JSON payload/results so later model-specific prompting/parsing remains outside the adapter. Settings uses KLOOP_ env vars, selected Region us-east-2 only; AWS clients are injected and caller-owned. Real Box authentication/client implementation remains the separate Box task.

Verification 2026-10-17: make test PASS (21 tests; JSON round-trips; memory/DynamoDB contracts with moto including >1 MB pagination; memory/S3 artifacts; botocore Stubber invocation, response-body closure and error propagation; fake Box version isolation; env config). make lint PASS (ruff check and format on application/test directories; existing POCs excluded). git diff --check PASS. Commit/push pending.

## Completed
Committed and pushed 14a9d4a54c896116458b97b5301bd4e04fae33e0 to withered-cobra after pull --rebase. All gates above pass. Full base/head, file list and evidence handoff appended to PR Context — withered-cobra (846fb942-136d-4b81-98f2-354a4926f1de). Only unrelated untracked AGENTS.md/CLAUDE.md remain.

## Verifier findings — wave 1 scaffold, 2026-10-17

### Verification Summary
- Verdict: APPROVED.
- Confidence: High for scaffold scope.
- Exact reviewed/tested head: 14a9d4a54c896116458b97b5301bd4e04fae33e0 on withered-cobra.
- Base: bf92eaf3a40d9debacdea1abbd0f607a6b27c25a (PR context task base, independently confirmed as HEAD parent).
- No failing criteria, accepted deviations, or spec ambiguity. Full application deployment/runtime criteria belong to later tasks.

### Acceptance Criteria Checklist
- VERIFIED — Python 3.12 + uv, ruff/pytest and required layout. Evidence: pyproject.toml, uv.lock, Makefile; kloop/, lambdas/, training/, web/, infra/, tests/ all tracked. Verification: static review and pytest runtime Python 3.12.13.
- VERIFIED — All listed schema fields. Evidence: kloop/schemas.py: Document file/version/name/text; Item kind/subject/statement/trigger_conditions/ordered steps/supporting_quote/source file+version/extractor/status (all four)/flag_reasons; Question all five kinds and train/dev/hidden splits; ModelVersion import_arn/status/manifest/scores; AskJob question/mode/status/answer/latency_ms; EvalReport with hash, split, per-question results and aggregate scores. Verification: field-by-field comparison to task Scope.
- VERIFIED — JSON round trips. Evidence: tests/test_schemas.py parameterizes Document, fact/procedure Item, Question, ModelVersion, AskJob and nested EvalReport/EvalResult. Verification: all round trips passed; rejection tests also passed.
- VERIFIED — Both storage implementations pass the same contract tests, DynamoDB via moto. Evidence: tests/conftest.py storage fixture parametrized memory/dynamodb and tests/test_contracts.py. Verification: round-trip/copy isolation, collection separation, sorted replacement/list/delete/missing behavior and >1 MB pagination all passed for both.
- VERIFIED — Interfaces and implementations/fakes. Evidence: kloop/ports.py Storage/Artifacts/ModelClient/BoxClient; adapters/aws.py DynamoStorage/S3Artifacts/BedrockModelClient; adapters/memory.py memory storage/artifacts, canned model and versioned Box fake. Verification: shared artifacts contract, Bedrock Stubber native JSON request/error propagation/body closure, fake model recording and Box version/copy isolation all passed. Real Box client intentionally belongs to separate task.
- VERIFIED — Environment config. Evidence: kloop/config.py BaseSettings with KLOOP_ prefix; deployment names/secret references/model/folder and selected Region us-east-2. Verification: test_env_config passed override and invalid Region rejection.
- VERIFIED — Pure kloop modules import no AWS SDK. Evidence: schemas.py, ports.py, config.py, memory adapter and package initializers; only adapters/aws.py imports boto3. Verification: imported all core modules and memory adapter in fresh process with boto3/botocore imports blocked; passed.
- VERIFIED — Required gates. Verification: make test && make lint exited 0; 21 pytest tests passed; ruff check passed and 13 files passed format check.
- VERIFIED — Existing poc/ untouched; no secrets committed by scaffold. Evidence: exact base/head diff contains 19 paths, none under poc/; manually reviewed scaffold sources/config/test fixture fake credentials and lockfile; credential-pattern scan of every changed committed file found zero AWS access keys/private keys/GitHub tokens/credential assignments/credential URLs. Secret IDs are references, not secret values. Verification: git diff base head -- poc/ empty; git diff --check clean. This is a bounded changed-file review, not a claim about all repository history.

### Evidence index
- Commit reviewed: 14a9d4a54c896116458b97b5301bd4e04fae33e0, Scaffold application layout, shared schemas and service adapters.
- Task note: 95f99466-dc52-42e3-b3ee-766e4d8ffa05.
- Context: 846fb942-136d-4b81-98f2-354a4926f1de; spec Goal/Decisions/Non-goals/Acceptance Criteria/Verification Plan read.
- Areas: all 19 scaffold paths, all application/test source files, project/lock/Makefile/gitignore.

### Tests/Commands Run
- make test && make lint → PASS (21 tests; ruff check/format).
- git diff --check bf92eaf3a40d9debacdea1abbd0f607a6b27c25a 14a9d4a → PASS.
- git diff bf92eaf3a40d9debacdea1abbd0f607a6b27c25a 14a9d4a -- poc/ → empty, PASS.
- rg -n 'boto3|botocore|kloop.adapters.aws' kloop → only adapters/aws.py:6.
- uv run --locked python with guarded __import__ denying boto3/botocore, importing kloop, schemas, ports, config, adapters.memory → PASS.
- Read-only Python scanner over git show head:path for each changed path → zero credential-pattern findings.
- git status --short → only pre-existing untracked AGENTS.md and CLAUDE.md. No tracked files changed by verification.

### Exact re-verify commands
At the reviewed head, run:
```sh
git rev-parse HEAD
make test && make lint
git diff --check bf92eaf3a40d9debacdea1abbd0f607a6b27c25a 14a9d4a54c896116458b97b5301bd4e04fae33e0
git diff bf92eaf3a40d9debacdea1abbd0f607a6b27c25a 14a9d4a54c896116458b97b5301bd4e04fae33e0 -- poc/
rg -n 'boto3|botocore|kloop.adapters.aws' kloop
git status --short
```

### Risk Notes
AWS behavior is tested with moto/Stubber, not live DynamoDB/S3/Bedrock. This meets the scaffold Definition of Done and does not establish deployed-runtime acceptance. No cloud resources created or changed; no code fixes.
