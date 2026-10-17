# Box client: CCG auth, files, versions, seeding

One Box client library used by every Lambda.

## Scope
Box Python SDK with **CCG** (client id, secret, enterprise id read from Secrets Manager). List the Halvard folder with file ids and version ids; download text (PDF/DOCX/MD/TXT); upload/overwrite files; write to `reports/`. `kloop box seed` uploads the knowledge pack; `kloop box edit --apply v2` applies the v2 edits (for rehearsing scenario 3). An in-memory fake with the same interface for tests.
Not in scope: sync logic, webhooks (sync task).

## Inputs
Scaffold; https://github.com/box/skills (box-sdk-development)

## Definition of Done
Fake fully tested; real client tested against Box when credentials exist (skipped otherwise); seed and edit commands work.

## Verification
`make test`; with credentials: `uv run python -m kloop box seed` then `kloop box ls`
