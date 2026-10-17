# End-to-end loop runner and demo script

One command runs the whole loop and a script walks through the three demo stories and the Box-sync finale.

## Scope
`kloop run`: seed Box → extract → review → teach facts (TensorFold) and train procedures (LoRA) → evaluate → promote. Demo script: (1) jargon question answered by learned model, missed by retrieval; (2) two-fact composition; (3) procedure: TensorFold fails, LoRA succeeds; finale: edit the handbook in Box, changes detected, old fact deleted, new fact taught, server restarted, new answer persists. Final report states plainly that fictional data proves the mechanism, not business value.

## Inputs
All earlier tasks.

## Definition of Done
A clean run on the remote host completes and writes the report; the demo script runs start to finish.

## Verification
`uv run python -m kloop run --source box` (or `--source local`); `uv run python -m kloop demo`
