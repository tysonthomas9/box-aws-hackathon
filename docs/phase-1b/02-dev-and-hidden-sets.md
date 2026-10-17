# 1b-2 Medical dev set, sealed test set and demo scenarios

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `04775487-6ca5-44f5-8dcf-296d5a3f8e34`. Task status: **not started**. Earlier progress entries are historical; later dated entries record updates.

Build new dev and sealed hidden question sets and six demo scenarios from the approved medical snapshot.

## Scope
Generate once from the snapshot (Kimi generates, GLM checks), then freeze by hash. Same mix as before: single facts, two facts combined, procedures (SOPs), "I don't know" questions and near-misses, and unrelated questions. Replace the Halvard pack scenarios with medical ones in the same order and shape: a fact, two facts, an SOP procedure, a rule supplied in the question, the document-change scenario chosen in 1b-1, and a decline. Evaluation code reads the new hashes; the old Halvard sets stay in history.

## Inputs
Task 1b-1 output; the pack task 9fcb8ca7-3f25-4063-89ac-6b6c75ed17a1; the evaluation task 31cfbb2b-f39f-43b3-8ea5-0823605c0ed7.

## Definition of Done
- About 30 dev and about 50 hidden questions; dev and hidden have no question overlap with each other or with training rows (lexical audit passes).
- Sealed hidden set is never shown to the training generator.
- `pack/demo-scenarios.json` rewritten for the medical company; each expected answer traces to an approved item.

## Verification
`make test && make lint`; the overlap audit report; hashes recorded in the spec.
