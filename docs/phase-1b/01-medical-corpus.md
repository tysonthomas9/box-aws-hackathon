# 1b-1 Medical corpus: sync, extraction and approved snapshot

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `eb3b99ca-0e08-4ae3-ac26-3d15eee19b3a`. Task status: **in progress**. Earlier progress entries are historical; later dated entries record updates.

Point sync and Box AI extraction at The Rubber Ducks `company-specific/` folder and produce an approved, immutable knowledge snapshot.

## Scope
Config for the source folder (id 428390666255, recursive), the extraction template/prompt for clinical, safety, quality and regulatory Word documents, auto-check thresholds, and a bulk auto-approve path that the Review screen still shows. Do not change training, evaluation or web code beyond config.

## Inputs
Spec Phase 1b section; the extraction task 631555a7-e757-4b6b-a82a-6460b253bbfc; the Box client task e9fa2502-748b-4049-ae95-ec481bcf4b49. Box secret: Secrets Manager box-hackathon/box-ccg (never print values).

## Definition of Done
- First a probe on 5 documents (one per subfolder) under $1, recorded with item counts and examples.
- Proves a webhook can be created on this folder and Box AI works on files owned by the other enterprise (or records the failure and stops to report).
- Full run over `company-specific/`: every document synced, items extracted, checks applied, approved snapshot written with a hash; per-folder counts and rejected-item reasons recorded in a note "Medical corpus snapshot".
- Picks one editable document plus a value inside it for the live "document changes" demo scenario, and records it (do not edit it yet).

## Verification
`make test && make lint`; the probe and full-run evidence files; snapshot hash reproducible from stored items.

## Probe preflight — 2026-10-17

Confirmed CCG service actor 53095120751 can read root 428390666255. Training boundary is company-specific folder 428391006380; public is excluded. Recursive inventory found 115 DOCX documents across clinical-medical, commercial-heor, pharmacovigilance, quality-manufacturing and regulatory-affairs (including nested CTD Modules 1–5). AWS plan confirmed FREE in us-east-2. Created webhook 8516978031 on company-specific using the coordinator-approved temporary callback, read it back, deleted it immediately and verified GET returns 404; no source edits or live signed delivery test. Evidence: poc/medical-corpus/evidence/probe/inventory.json and webhook.json. First native Box AI extraction is underway.

## Implementation progress

Added narrow bounded DOCX paragraph/table-text decoding in kloop/box/client.py with no dependency changes; existing UTF-8 behavior remains. Added medical prompt/source constants and a five-file, resumable native Box AI probe. Probe pins versions by checking before/after native extraction, saves raw responses/rows/pinned source text, fails on access/incomplete/schema/model errors without fallback, and records literal quote failures. Focused verification: 47 tests pass (tests/test_medical.py plus existing tests/test_box.py). Capacity issue found: current aggregate extraction/review state is limited to 350 KB and a snapshot to one DynamoDB record; probe will quantify whether full corpus exceeds this before any full run.
