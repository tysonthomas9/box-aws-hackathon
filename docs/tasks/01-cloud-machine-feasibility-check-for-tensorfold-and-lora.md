# Cloud machine feasibility check for TensorFold and LoRA

Prove, in about an hour, that the chosen cloud machine can teach TensorFold one fact and run a LoRA training step. Everything else depends on this.

## Scope
On the remote host Tyson provides: install TensorFold (brew on macOS, linux-aarch64 archive on a GB10-class machine), download Nemotron 3.5 Lightning MLX 4-bit, make a copy, start the server with --slide and an API key. Teach "On the Halvard X200, error E42 means the fan has failed." Ask a held-out wording, restart the server without --slide, ask again, then roll back. Record time per fact, peak memory, disk used. Run a tiny LoRA training job on the same host (MLX on Mac, PEFT on NVIDIA). Write a runbook note with exact commands. Do not touch any other machine or stack.

## Inputs
TensorFold docs: /Users/tyson/codebase/code-agents/sept/TensorFold/docs/living-weights.md

## Definition of Done
Runbook note exists; the fact is recalled after restart, or the failure is documented with the reason and a recommended alternative machine.

## Verification
Transcript of learn, ask, restart, ask, rollback commands in the runbook note.
