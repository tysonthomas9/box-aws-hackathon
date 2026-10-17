# POC 3 — Box CCG app, Box AI extraction and webhook delivery

Prove the Box side works on Tyson's tenant before building the sync service.

## Scope
With Tyson's Box Platform app (CCG): authenticate, confirm the service account can access a test folder (collaboration), upload 3 Halvard documents, call Box AI `extract_structured` with a table field for a list of facts/procedures (one file per call, pinned model), and score extraction against the gold items. Create a webhook on the folder pointing at a throwaway API Gateway + Lambda echo endpoint in us-east-2, edit a file, confirm delivery and verify the signature. Record plan/AI-unit errors exactly if Box AI is unavailable. Delete the webhook and the echo stack afterwards.

## Inputs
Box developer docs; [Spec](../spec.md).

## Definition of Done
Runbook note: auth steps, required scopes, extraction output sample and recovery rate, webhook delivery timing, and any blockers; all test resources removed.

## Verification
Transcript and outputs in the runbook note.
