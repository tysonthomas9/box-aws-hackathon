> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `dcb4c828-5a3b-4ff2-a17f-ba26ce6d88fc`. Earlier progress entries are historical; later dated entries record updates.

## Final result

POC completed with the coordinator-authorized temporary developer token. Three uploads and pinned AWS-model Box AI extraction passed, recovering 3/3 gold items (6/6 obligations). Real webhook delivery arrived 1.641030 seconds from upload start and 0.749427 seconds after the upload response. Signature headers and signing keys were absent: signature verification remains pending. CCG admin authorization remains an open phase 1 item. All created cloud and Box resources were removed and absence verified. Historical checkpoints below describe the earlier blocked attempt.


Task: 2617ddfa-ab6b-42c3-9262-c50b22a82f9e

Scope: runtime CCG secret; user subject; only a new owned test folder; 3 mini-pack documents; pinned extraction; throwaway us-east-2 receiver; delete all owned test resources. No other Box content will be read.

Status: preflight. Cleanup is already authorized by coordinator.

## Result — blocked at CCG authorization

Runtime secret retrieval succeeded with profile `box-hackathon`, selected Region `us-east-2`. All four required CCG fields exist; `box_subject_type=user`. No secret values or tokens were printed or persisted. One POST to `https://api.box.com/oauth2/token` returned HTTP **400**, exact body:

```json
{"error":"invalid_grant","error_description":"App is not yet authorized for use"}
```

Tyson or a Box administrator must authorize the existing CCG app in the Box Admin Console. For the intended user subject, confirm App + Enterprise Access and Generate User Access Tokens; reauthorize after changing configuration. Then rerun `python3 poc/box/preflight.py` before resuming this task. [Box CCG setup](https://developer.box.com/guides/authentication/client-credentials/client-credentials-setup/) and [CCG user-subject requirements](https://developer.box.com/guides/authentication/client-credentials/).

Required POC permissions: read/write files and folders, Manage Webhooks, and the Box AI permission for extraction. These scopes are requirements, not verified app configuration.

No primary/secondary/webhook-named signing-key fields exist in this CCG secret. Keys may exist elsewhere; signature verification remains pending the Developer Console keys stored in Secrets Manager, never chat.

## Evidence and verification

- `aws configure get region --profile box-hackathon`: `us-east-2`, matching coordinator-confirmed selected Region.
- `aws freetier get-account-plan-state --profile box-hackathon --region us-east-2`: FREE / ACTIVE, $100 remaining credits. Project has not upgraded to PAID.
- One runtime-secret CCG probe: FAIL, exact response above. No second auth attempt.
- `poc/box/preflight.py`: reusable credential-safe preflight; Python AST parse PASS and `git diff --check` PASS. The saved script itself has not been executed against Box; evidence records the equivalent initial probe.
- `poc/box/evidence/preflight.json`: captured bounded result and cleanup ledger.

## Remaining POC work

Three document uploads, pinned-model table extraction, gold recovery score, webhook creation, file edit, delivery timing and signature verification are **NOT RUN** because no access token could be obtained. No extraction sample or recovery percentage can be claimed. Box AI plan/AI-unit availability is unknown; no AI request reached that endpoint. Pack was read from `poc/company-knowledge/pack.json`; no changes to POC 2.

## Cleanup ledger

Box folders/files/webhooks: none created. AWS API Gateway/Lambda/IAM/log resources: none created. Nothing needs cloud deletion. Existing Secrets Manager secret retained unchanged. Temporary local probe `/tmp/box-poc3-auth.py` removed. No other Box content was listed, read, changed or deleted. No Support cases or quota requests; no paid resources created.

## Resumed with temporary developer token
Coordinator authorized developer_token from the same runtime secret (generated about 06:12 UTC, expires about 07:10 UTC). CCG remains a phase 1 open item. Using official box/skills guidance before coding; Box steps first, then temporary receiver and cleanup. Resume base 95fbdf43244f5af012beb05c761d6d3127e11dbf.

## Document and extraction proof

Developer token confirmed GET /users/me 200 as Tyson, user ID 53094349916. Created only folder 428389178330 (`Halvard POC3 20261017-061328`). Files: kestrel.txt 2532291966730 (F01), nacre.txt 2532302130149 (F02), e42.txt 2532291993130 (P01), generated verbatim from POC2 pack.json records. Read-after-write parent/SHA1 checks passed; new folder shared_link=null, has_collaborations=false. No other Box content listed.

The model in the current REST documentation example (`azure__openai__gpt_4o_mini`) was rejected HTTP400 by the live enum validator on all three requests. Exact errors retained in extraction-model-rejected.json. Corrected once to returned supported AWS model `aws__claude_4_5_haiku`; all three requests returned 200 / completion_reason=done and response model/provider exactly matched aws__claude_4_5_haiku/aws. No metadata template created; explicit table schema with subject/statement columns, one file per call, >=2second pacing.

Direct gold inspection recovered 3/3 items, 6/6 fact/procedure obligations (100% on this tiny sample). E42 yielded four rows preserving measure-first, low-pressure restore/retest, do-not-replace and high-pressure/persistent-fault replacement conditions. No invented statements observed. Score is not a broad benchmark; immutable model revision unavailable. Raw extraction and score artifacts under poc/box/evidence.

Guidance used: official [box foundation skill](https://github.com/box/skills/blob/84320fd8984b95cab430335cd341d8314c14bbcb/skills/box/SKILL.md), box-sdk-development and box-integration-best-practices at the same commit; mandatory guardrails plus auth-and-setup, content-workflows, ai-and-retrieval, rest-calls, webhooks-and-events references. Coordinator explicitly authorized REST Bearer flow, isolated writes/edit/cleanup, superseding redundant skill confirmation steps. Followed current Box upload and extract_structured docs, retained the live model-enum correction rather than hiding it.

Receiver setup encountered IAM propagation failure on initial CreateFunction (`The role defined for the function cannot be assumed by Lambda`); the owned role/log group are in the cleanup ledger and setup resumes using those same IDs.

## Webhook delivery and cleanup result

Registered webhook 8516747068 on owned folder 428389178330 for FILE.UPLOADED. Receiver: regional REST API 76khft1ll9, Lambda/role `box-hackathon-poc3-20261017-061328`, log group `/aws/lambda/box-hackathon-poc3-20261017-061328`, all in us-east-2 (IAM role global). Every taggable resource was tagged project=box-hackathon; inline policy/resource/method/integration/deployment have no independent tag surface. Role permits writes only to the owned log group. Receiver is a temporary public HTTPS capture-only endpoint, throttled to 1 request/second with burst 2; no downstream effects or secret access.

Initial handler incorrectly required target folder in the event webhook object, so the first delivery was rejected; original logs/edit preserved. Box event payload has webhook ID but no target field. Corrected capture checks to exact owned webhook ID and owned source IDs, then edited the file again. No broad content access was added. Second edit uploaded file version 2810011275730 and received a real FILE.UPLOADED event. Authoritative timing: upload start 06:16:04.073322Z; receipt 06:16:05.714352Z; 1.641030seconds from start, 0.749427seconds after upload response. Event 6d12b872-5789-4207-b89b-1f0e7fa6bb9a, delivery db9c77bf-d372-494f-986c-59f0e9ee8e1f. Read source metadata after receipt confirmed owned parent and current version.

Neither BOX-SIGNATURE-PRIMARY nor SECONDARY was present. Runtime secret still has no signing-key fields. This proves observed delivery and timing, not cryptographically authenticated origin. Timestamp/HMAC, invalid-signature rejection and durable duplicate suppression are NOT validated; no downstream action exists in this echo POC. For phase 1, generate signature keys in Developer Console > Webhooks and store them in Secrets Manager; implement HMAC over raw body followed by delivery timestamp bytes, compare safely and enforce freshness. [Official signature guidance](https://developer.box.com/guides/webhooks/v2/signatures-v2). Do not paste keys into chat.

Cleanup completed 2026-10-17T06:16:41.943925Z: deleted webhook and verified404; inspected exact owned folder contents before deletion, trashed and permanently purged it, confirmed active/trash404 and all three files404; deleted API, Lambda, inline policy, IAM role and log group, then confirmed API NotFoundException, Lambda ResourceNotFoundException, role NoSuchEntity and no matching log group. Temporary ZIP directories under /tmp automatically removed. Original secret retained unchanged. No other Box content read or changed. No Support/quota requests or action approaching $10. AWS free plan remained as checked; exact billed dollars and Box AI units were not exposed or measured.

## Reproduction and verification

Live stages run: `python3 poc/box/run.py documents`; corrected `python3 poc/box/run.py extract`; `python3 poc/box/receiver.py` (initial IAM propagation failure, then resume with owned role); `python3 poc/box/webhook.py` (initial capture gate correction, then second edit); `python3 poc/box/cleanup.py`. ZIP update and log-collection commands were executed inline and evidence retained. Credentials always read from Secrets Manager in process, never command arguments, logs or persisted output.

Final offline gate: `PYTHONDONTWRITEBYTECODE=1 python3 poc/box/verify.py` PASS (source/pack hashes, one-file table schema, returned pinned model, all three gold items, webhook/file IDs, timing, cleanup absence); Python syntax and `git diff --check` PASS. Runtime-value scan of all poc/box files found no client_secret/developer_token values. No CI run, PR or base CI failure assessment performed. This is bounded Box integration proof, not durable server authentication, signature security or production sync acceptance.

## Phase 1 CCG authorization handoff — official troubleshooting addendum

Read the queued coordinator-requested [troubleshooting reference](https://github.com/box/skills/blob/84320fd8984b95cab430335cd341d8314c14bbcb/skills/box/references/troubleshooting.md) after completing cleanup. It does **not** contain the exact phrase `App is not yet authorized for use` or a CCG-specific400 recipe. It says to capture acting identity, endpoint/method, object ID, minimal payload, status and exact body before changes; common auth causes include wrong actor, missing permissions, expired tokens and unconfirmed access changes. Those diagnostics were retained. The CCG-specific fix comes from the current official setup guide, not from an invented troubleshooting entry.

Tyson/Box administrator next:

1. Open the existing app in Developer Console > Configuration. Confirm Server Authentication / Client Credentials Grant, set App Access Level to App + Enterprise Access, and enable Generate User Access Tokens for the intended managed-user/admin subject. Keep only the required content, AI and webhook scopes; save changes.
2. Use the authorization prompt on Configuration. Current Box docs say free developer apps normally authorize automatically; if that failed, use the displayed authorization prompt. Enterprise developers submit for admin approval; admins/co-admins can authorize directly. Some UI versions expose this through Authorization > Review and Submit. Tenant type was not established by this POC; the exact live400 shows authorization is still missing.
3. A primary admin or permitted co-admin opens Admin Console > Platform > Platform Apps > Server Authentication Apps, locates this app, and selects View to review the authorization/enablement options and authorize/enable the app. Reauthorize after changing scopes or app settings. This is the CCG/server-app path; user-auth OAuth enablement is a different tab.
4. Rerun `python3 poc/box/preflight.py` to request CCG with runtime client_id/client_secret, box_subject_type=user and the configured box_subject_id. A200/token_received result must precede phase1 deployment; then validate `/users/me` with that runtime token, without printing or saving it. Developer token success does not prove CCG.

Sources: [current CCG setup, user requirements and common errors](https://developer.box.com/guides/authentication/client-credentials/client-credentials-setup/); [exact current Admin Console navigation](https://support.box.com/hc/en-us/articles/360044196653-Managing-platform-apps). No console action or new token request was performed for this addendum. Existing POC verdict, commit and completed task status are unchanged.
