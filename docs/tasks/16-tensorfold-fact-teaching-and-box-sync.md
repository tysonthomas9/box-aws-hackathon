# TensorFold fact teaching and Box sync

**Phase 2.** A Lambda in the VPC calls the TensorFold server on the EC2 Mac over its private address. Teach approved facts one at a time through TensorFold, record what stuck, and keep the model in step with Box edits.

## Scope
Client for /v1/slide/learn (server-sent events): teach each approved fact, record kept or undone with TensorFold's message, linked to the Box file version it came from. Fact registry persisted locally and in Box reports/. Sync: when `changes(since)` reports an edited or deleted file, delete affected facts and teach the new versions. Snapshot and rollback wrappers. Procedure probe: send procedure statements to TensorFold too, so the evaluation can show whether it learns them. Not in scope: LoRA.

## Inputs
Feasibility runbook, document source, review records, TensorFold docs.

## Definition of Done
Against a stub SSE server in tests, teach, undo, delete and re-teach paths all work; against the real host, the pack's facts are taught and the registry shows kept and undone counts.

## Verification
`uv run pytest -q tests/test_tensorfold*.py`; `uv run python -m kloop facts teach`; `kloop facts sync`
