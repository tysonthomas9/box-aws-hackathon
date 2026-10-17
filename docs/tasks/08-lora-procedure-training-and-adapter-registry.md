# LoRA procedure training and adapter registry

Teach procedures (conditional, multi-step behavior) with LoRA, the part TensorFold cannot learn, and keep every adapter as a numbered version.

## Scope
Build SFT examples from approved procedures (situation in, ordered steps with short reasoning out). Train on the remote machine: MLX LoRA if it is a Mac, PEFT/TRL if it is NVIDIA, chosen from the feasibility-check result. Base model per spec assumptions. Versioned registry (v1, v2...) with parent, data hash and hyperparameters. Reload proof: a fresh process loads the adapter and reproduces greedy outputs. Optional cross-check: also train on fact statements so the evaluation can show whether LoRA learns single facts.
Not in scope: DPO or RL.

## Inputs
Feasibility-check runbook note; knowledge pack; review records.

## Definition of Done
One command trains an adapter version on the remote host, registers it, and passes the reload check.

## Verification
`uv run python -m kloop lora train` then `kloop lora reload-check --version latest`
