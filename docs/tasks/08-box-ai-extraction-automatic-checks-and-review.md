# Box AI extraction, automatic checks and review

Extract candidate facts and procedures from changed files, approve the safe ones automatically, and flag the risky ones for a person.

## Scope
- Extraction: Box AI `POST /ai/extract_structured` (one file per call; pinned model via `ai_agent`); check whether a list of items per file works (JSON-array field or `/ai/extract` with a JSON prompt) and document the choice. Fallback extractor: Claude on Bedrock, same output. Compare with items already approved from the same file: new, changed, retired, same.
- Automatic checks: (1) supporting quote found verbatim in the file; (2) every name, number and date in the item appears in the quote; (3) no contradiction with another approved item (same subject and attribute, different value); (4) valid structure and the fact names its subject.
- Review modes (setting): `off` (approve everything that passes, log flags), `exceptions` (default: auto-approve passes; flagged, changed values and retirements wait for a person), `all`.
- Review API used by the UI: list, approve, edit, reject, with flag reasons. Simulated reviewer for tests.
Not in scope: UI.

## Inputs
Box client, schemas, knowledge pack.

## Definition of Done
On the knowledge pack, extraction (Box AI when credentials exist, fallback otherwise) recovers most gold items (report the rate); each check has unit tests; the v2 edits flag exactly the changed limit and the Atlas retirement.

## Verification
`make test`; `uv run python -m kloop extract --file handbook.md`
