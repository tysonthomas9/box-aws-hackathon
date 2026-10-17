# Phase 2: TensorFold feasibility on EC2 Mac

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `486fe5ed-d16c-484e-93bc-ede8569e5871`. Task status: **not started**. Earlier progress entries are historical; later dated entries record updates.

Prove TensorFold can teach one fact and keep it after a restart on an AWS EC2 Mac.

## Scope
Once Tyson has the Mac Dedicated Host quota: provision `mac-m3ultra.metal` (Terraform, private subnet, SSM access only). Install TensorFold, download Nemotron 3.5 Lightning MLX 4-bit, copy it, start with --slide and an API key. Teach "On the Halvard X200, error E42 means the cooling fan has failed.", ask a held-out wording, restart without --slide, ask again, roll back. Record time per fact, memory, disk. Runbook note with exact commands. Release the host when done unless phase 2 continues.

## Inputs
/Users/tyson/codebase/code-agents/sept/TensorFold/docs/living-weights.md

## Definition of Done
Runbook note; fact recalled after restart, or failure documented with reason.

## Verification
Transcript in the runbook note.
