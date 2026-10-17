# 1b-3 Train, import and evaluate on the medical corpus

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `8c963360-1aa4-493e-a00b-6a9703f8a341`. Task status: **not started**. Earlier progress entries are historical; later dated entries record updates.

Run the training pipeline end to end on the medical snapshot with the winning model size, then evaluate all three modes.

## Scope
Training data generation from the approved snapshot, SageMaker LoRA, Bedrock import (32K context, re-import once on ModelNotReady), dev gate and promotion, hidden-set report. Also train the v2 version for the document-change scenario (after applying the 1b-1 edit to a copy of the snapshot, not to Box).

## Inputs
Tasks 1b-1 and 1b-2; the training task 2fd9c199-7f95-45ea-868f-ae36aeb88d90; the model experiment decision.

## Definition of Done
- v1 and v2 models imported and serving; at most 3 imports exist at any time; old imports cleaned up through the ledger.
- Dev and hidden results for without, trained and search, with untold-answer counts, in a note "Medical results".
- Spend recorded; each single action under $10.

## Verification
`make train-live` and `make eval-live` evidence; the cleanup ledger shows no orphaned resources.
