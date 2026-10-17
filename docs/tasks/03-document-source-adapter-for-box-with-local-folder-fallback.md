# Document source adapter for Box with local-folder fallback

One interface for listing, reading and writing documents, backed by Box or by a local folder, and able to tell which files changed since the last run (needed for the Box-sync demo).

## Scope
`DocumentSource`: list folder, read text (PDF/DOCX/MD/TXT), write file, read file version id, and `changes(since)` returning edited, added and deleted files by comparing version ids. BoxSource with the official Box Python SDK (developer token or CCG from env vars). LocalSource with the same layout (handbook/, runbooks/, reviews/, reports/), using content hashes as versions. A seed command that uploads the knowledge pack to a Box folder, and a command that applies the pack's "v2 edits" to simulate someone editing the handbook. Not in scope: retrieval, models.

## Inputs
Schemas from the scaffold task. Box skills: https://github.com/box/skills

## Definition of Done
LocalSource fully tested including change detection; BoxSource implemented and skipped in tests without credentials; config switch selects the source.

## Verification
`uv run pytest -q tests/test_source*.py`; with Box credentials, `uv run python -m kloop source seed` then `kloop source edit --apply v2` then `kloop source changes` lists the edited files.
