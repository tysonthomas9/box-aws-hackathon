# Phase 2: add the TensorFold track to inference, evaluation, UI and demo

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `8dc08ec9-1a14-4d9a-a688-f88552742efa`. Task status: **not started**. Earlier progress entries are historical; later dated entries record updates.

Bring TensorFold into every phase 1 surface so facts and procedures can be compared.

## Scope
Inference: original and taught Nemotron modes. Evaluation: TensorFold columns and the facts-vs-procedures matrix (TensorFold taught the E42 procedure text; LoRA taught the E42 fact). UI: per-fact teaching timeline (kept / undone with reason), TensorFold columns on Ask and Hidden test. Demo: scenario 4 and the instant Box-edit version of scenario 3. Questions route to the facts model or the procedures model, labelled in the UI.

## Inputs
Phase 1 code; TensorFold feasibility runbook; [Demo scenarios](../scenarios.md).

## Definition of Done
Scenario 4 runs end to end and the matrix appears in the report and UI.

## Verification
`uv run pytest -q`; `uv run python -m kloop demo --phase 2`
