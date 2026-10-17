# POC 3 — Box CCG app, Box AI extraction and webhook delivery

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `2617ddfa-ab6b-42c3-9262-c50b22a82f9e`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Prove the Box side works on Tyson's tenant before building the sync service.

## Scope
With Tyson's Box Platform app (CCG): authenticate, confirm the service account can access a test folder (collaboration), upload 3 Halvard documents, call Box AI `extract_structured` with a table field for a list of facts/procedures (one file per call, pinned model), and score extraction against the gold items. Create a webhook on the folder pointing at a throwaway API Gateway + Lambda echo endpoint in us-east-2, edit a file, confirm delivery and verify the signature. Record plan/AI-unit errors exactly if Box AI is unavailable. Delete the webhook and the echo stack afterwards.

## Inputs
Box developer docs; [Spec](../spec.md).

## Definition of Done
Runbook note: auth steps, required scopes, extraction output sample and recovery rate, webhook delivery timing, and any blockers; all test resources removed.

## Verification
Transcript and outputs in the runbook note.

[POC 3 runbook — Box authentication, extraction and webhooks](../pocs/poc-3-runbook.md)

## Checkpoint
Blocked: Box CCG returns HTTP400 invalid_grant / App is not yet authorized for use. No resources created. Preflight and evidence committed as ea1a0177af54c9080c4f760b8956caff9b1b8ab9; Python syntax/diff checks passed. Full POC remains uncompleted pending Box administrator app authorization. See runbook dcb4c828-5a3b-4ff2-a17f-ba26ce6d88fc.

## Completed POC result

Temporary developer token worked as Tyson. Three isolated uploads/read-after-write checks passed; Box AI pinned aws__claude_4_5_haiku extracted3/3 gold items and6/6 obligations. Real FILE.UPLOADED delivery arrived1.641030s from upload start. All test resources deleted and absence verified. Final offline evidence/syntax/diff/credential-scan checks passed. Commit4bbf06c7c8cc392df0f534ffc24c98329eb2d52d.

Allowed open items: CCG still needs admin authorization; no signing keys or signature headers, so signature verification pending. These are phase1 follow-ups, not claims of proof. See final runbook for exact IDs, model-enum correction, errors and timings.
