# Box AI extraction, automatic checks and review

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `631555a7-e757-4b6b-a82a-6460b253bbfc`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Turn Box documents into reviewed facts and procedures.

## Scope
`kloop/extract/`: Box AI `extract_structured`, one file per call, pinned model (as in POC 3), table fields for facts and procedures with supporting quotes. GLM-5 on Bedrock as the fallback when Box AI errors. Automatic checks: the quote exists in the document text, required fields are present, no duplicate, conflict with an approved item (changed value), source file deleted (retire). Clean items are auto-approved; flagged, changed and retired items go to review. Review actions: approve, edit, reject; review mode off/exceptions/all.
Not in scope: sync triggering, UI.

## Definition of Done
Tests with recorded Box AI responses; on the knowledge pack, extraction recovers ≥90% of gold items; the v2 edit flags exactly the changed limit and the Atlas retirement.

## Verification
`make test`; `make extract-live` against the seeded folder.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Owns the item identity model** (extend `kloop.schemas`): stable item/attribute ids, source-version provenance, review decisions kept separate from effective item status, and immutable approved-snapshot hashes used by training. Subject/statement text alone must not be the identity.
- An extraction **omission does not retire** an item; only a deleted source file or an explicit reviewed retirement does.
- Box AI's pinned model is AWS-hosted Claude Haiku inside Box. Note this in the docs (we have no *direct* Bedrock Claude dependency).
- DoD uses the frozen pack's v2 edit (an existing changed value and an existing retirement).


## Interface agreed with the sync task (2026-10-17)
Implement the sync task's Protocol `kloop.sync.ports.Extraction` (a reusable `FakeExtraction` is there too): `Extraction.process(file_id, version_id) -> int` (durably reconcile items and reviews for that file version; preserve rejected decisions; return the change count) and `Extraction.retire(file_id) -> int` (durably propose retirement; preserve rejected decisions). Both must be idempotent; sync checkpoints only after they succeed.

## Implementation started
Read the complete task, phase 1 review amendments, sync Protocol and PR context. Working from fc54528 on the existing shared branch; no branch switch. Scope: kloop/extract, identity/review/snapshot schemas, focused tests, make extract-live. Live proof will use a uniquely named service-account folder with a durable reserve/create/verify/resolve ledger and exact-owned cleanup. No hidden questions are used.

## Implementation progress
Implemented Box table extraction pinned to aws__claude_4_5_haiku, pinned source content, regional zai.glm-5 fallback, stable item/attribute identities with explicit existing-item references, atomic revision-CAS durable knowledge/review state, review actions/modes, and immutable content-addressed approved snapshots. Sync factory: KLOOP_EXTRACTION_FACTORY=kloop.extract.runtime:factory.

Initial live evidence: 12/13 conservative gold recovery (92.3%), exact changed_value/source_deleted pair, rejection replay unchanged, all owned active and trash objects cleaned. First probe called the retirement hook directly; second probe actually deleted the owned Quartz source before retirement. Final-code live rerun now in progress, including raw Box response capture and code/source hashes.

Focused tests now cover memory and moto DynamoDB CAS, ambiguous-write replay, required fields/quotes/procedures, duplicates/conflicts, explicit retirement, omission safety, rejection persistence, restoration and snapshots. Full normal and credential-free gates are running. Persistent get_review_mode/set_review_mode supplied to web agent; snapshot algorithm and storage contract supplied to training agent. No deployment/runtime acceptance claimed.

## Live scorer correction
Final-code run 33fd95aad1d449b2a053bd9bd5928567 stopped at recovery 11/13 because the scorer treated underscores as part of a word: correct Vela/Quartz rows used subjects vela_export_files and quartz_recovery_package. Their statements contained the exact gold answers; extraction was correct. Corrected subject tokenization only (underscores and spaces are equivalent), added a regression requiring the correct cabinet value, retained the failed run and its cleanup ledger. A new complete live run will verify the corrected scorer and v2 path; no cherry-picked evidence is discarded.

## Final live proof
`make extract-live` PASS, 2026-10-17T07:24:41Z–07:25:55Z; evidence `poc/extract/evidence/d7896b2cfbfb447dad8f172430d581bd/`. Recovered 13/13 gold items (100%), including all procedures under a conservative complete-rule check. Exactly changed_value for Sable F06 and source_deleted for Quartz F10. The owned Quartz file was actually deleted in Box before retire(); rejected decisions survived both hooks replaying with no effective snapshot change. All 14 ledger entries (folder + source files) cleaned, each verified absent from active storage and trash. Prior attempts, including scorer failure, remain preserved. No AWS resources created, no webhook registered. CCG service-account secret reused. AWS plan query returned FREE/ACTIVE; all regional calls us-east-2.

Commit `4e9035f0a067d293e0ca46329f9488f4e9cdd5ed`, parent `82083ae9202bb257a23b71024fee60d01740dcd2`. Staged only extraction paths and exact extraction hunks in Makefile/schemas/test_schemas; web/training/model-experiment edits remain untouched. `git pull --rebase origin withered-cobra` in an owned detached /tmp worktree reports up to date. Exact committed-head normal `make test && make lint` PASS (166 tests, Ruff check/format). Credential-free exact-head gate running. Shared working tree normal/credential-free tests PASS 220; its transient active web-format failure is separately owned and not presented as a base failure.

## Completed
Pushed commit 4e9035f0a067d293e0ca46329f9488f4e9cdd5ed to origin/withered-cobra after pull --rebase; remote ref verified. Exact committed-head normal and credential-free make test && make lint both PASS (166 tests each, Ruff check and format). Focused extraction suite: 39 tests. Final live run: 13/13 gold, exact v2 proposals, rejection replay preserved, every owned Box folder/file active+trash absent. All four test ledgers cleaned, including the retained scorer-failure run. Exact-owned /tmp verification worktree removed; no extraction changes remain unstaged. Full PR context appended to note 846fb942-136d-4b81-98f2-354a4926f1de before reporting.

Limits/handoff: 350 KB bounded atomic demo store; snapshots/mode/review service interfaces sent to web/training. Deployed Lambda/API/IAM wiring and real webhook timing are later-task work. GLM fallback is covered offline, not a forced live provider-error run. No PR created (coordinator-owned; existing no-PR-until-asked rule). Evaluation agent notified that its Makefile include should land in its own commit, since extraction is already pushed.

## Verifier findings — extraction, 2026-10-17

Verdict: NOT APPROVED (high confidence). Reviewed pushed branch withered-cobra at 7e68a5b4232aa773b490321f4df7d7c9a1389287; extraction implementation 4e9035f0a067d293e0ca46329f9488f4e9cdd5ed, base 82083ae9202bb257a23b71024fee60d01740dcd2. Extraction source/tests unchanged between implementation and reviewed HEAD.

Verified: credential-free `make test && make lint` PASS (280 tests, Ruff check/format). The 39 extraction tests cover recorded Box responses, ≥90% recovery (13/13), exact frozen v2 changed_value/source_deleted pair, pinned Box model, regional fallback request, identity/provenance, snapshots, omission safety, replay and review actions. Saved live run d7896b2cfbfb447dad8f172430d581bd has matching current code/source hashes; independently recomputed 13/13 recovery from its snapshot and all ledger rows are recorded cleaned. No new live AWS/Box calls; `make extract-live` intentionally not re-run under verifier no-spend instruction.

Failing scope criterion: source file deleted (retire); flagged, changed and retired items go to review; approve/edit/reject in off/exceptions/all modes. At kloop/extract/service.py:186-188, retire() visits only approved effective items. A pending new item has no effective item; deletion records sources[f].deleted=True but creates no superseding review. At :245-265, decide() does not check that deleted state, so approve/edit can insert it into an approved training snapshot after deletion. Repro: all-review mode → process(f,v1) → capture pending upsert → retire(f) returns 0 → approve pending upsert → snapshot contains 1 approved item from the deleted source. Reproduced entirely with fake Box/extractor + memory repository.

Minimal fix requested from implementor agent-03118cff-c041-44cd-8e66-01bb2708c2df: prevent approval/edit of stale pending upserts after source deletion; cover initial pending item and a new pending attribute alongside existing approved items; preserve reject/replay and restored-source behavior. Fix request sent; verifier watch automatically armed.

Exact re-verify commands (run with AWS/Box/KLOOP environment entries removed, AWS_EC2_METADATA_DISABLED=true, AWS_CONFIG_FILE=/dev/null, AWS_SHARED_CREDENTIALS_FILE=/dev/null):
- `uv run --locked pytest tests/test_extract.py` (include new memory + moto deletion regressions)
- `make test && make lint`
- `git ls-remote origin refs/heads/withered-cobra` and `git rev-parse HEAD` to pin pushed fix.

Pending fix; do not mark this task verified complete. No spec ambiguity blocks review. Full system deployment acceptance is outside this task.

## Verifier repair: deleted source with pending upserts
Reproduced all eight memory/moto approve/edit regressions failing before the fix: a pending initial item or new attribute could be approved after retire() marked its source deleted. Added a decision-time guard that blocks approval/editing of pending upserts from deleted sources. Rejection remains allowed, retirement approvals remain allowed, and the existing source-epoch/supersession path permits restored/re-extracted sources to be reviewed normally. No live AWS/Box calls. Focused credential-free extraction suite PASS 47 tests; full normal and credential-free gates running. Scope only kloop/extract/service.py and tests/test_extract.py.

## Deleted-source pending-upsert repair — 2026-10-17T07:43Z
Task 631555a7-e757-4b6b-a82a-6460b253bbfc; PR none. Base 7e68a5b4232aa773b490321f4df7d7c9a1389287; repair head 696c1db61e469702fac848cae1d16dbef7651c86. Only kloop/extract/service.py and tests/test_extract.py changed.

Before: in review-all mode an initial pending upsert (or pending new attribute beside approved items) could be approved/edited after retire marked its source deleted. All eight new memory/moto regressions failed before the repair. After: decide blocks approve/edit for a pending upsert while sources[file_id].deleted is true, before applying edits or effective state. Rejections and idempotent decisions remain intact; restoration plus re-extraction produces a fresh actionable review, and earlier rejections stay rejected. Decision and deletion race through the existing revision CAS.

Gates run 2026-10-17T07:42Z: credential-free focused tests/test_extract.py PASS 47; normal make test && make lint PASS 288 and both Ruff gates; credential-free full make test && make lint PASS 288 and both gates. Child environment stripped AWS/Box/KLOOP_BOX and secret/token/credential/password/private-key variables, using /dev/null AWS config/credentials, metadata disabled and BOTO_CONFIG=/dev/null. git diff --check PASS. No known pre-existing gate failure; gh run list for base returned [], so no base CI failure link exists.

Pulled --rebase from origin/withered-cobra in a task-owned detached /tmp worktree (up to date), then pushed repair; remote head verified and exact-owned worktree removed. No branch switching or unrelated edits/staging in the shared checkout. No live AWS/Box calls or resource changes. Earlier 13/13 live evidence belongs to the prior extraction implementation; this review-only repair is supported by offline memory/moto regressions, not a refreshed live run, as requested by verifier.

## Verifier findings — extraction re-verification, 2026-10-17

### Verification Summary
- Verdict: APPROVED. This supersedes the earlier NOT APPROVED finding for this task.
- Confidence: High.
- Verified pushed repair: 696c1db61e469702fac848cae1d16dbef7651c86; tree bf64a2f317c548a5f1055062cbdc106bcdadf219. Repair base 7e68a5b4232aa773b490321f4df7d7c9a1389287; original extraction implementation 4e9035f0a067d293e0ca46329f9488f4e9cdd5ed, original base 82083ae9202bb257a23b71024fee60d01740dcd2.

### Acceptance Criteria Checklist
- ✅ VERIFIED: Tests with recorded Box AI responses and ≥90% frozen-pack gold recovery.
  - Evidence: tests/fixtures/extract/{recorded,raw-recorded}.json; test_recorded_gold_and_exact_v2_flags_and_rejected_replay; test_recorded_responses_match_pinned_model_and_frozen_source_text. Saved live run poc/extract/evidence/d7896b2cfbfb447dad8f172430d581bd.
  - Verification: independent offline tests pass; independently recomputed saved-snapshot recovery 13/13 (100%), checked recorded raw-response/source relationships and saved source hashes.
- ✅ VERIFIED: Frozen v2 edit flags exactly the existing changed value and retirement; unchanged replay changes nothing.
  - Evidence: frozen pack/v2/changes.json; tests identify Sable F06 changed_value and Quartz F10 source_deleted and preserve the initial approved snapshot until review.
  - Verification: recorded memory/moto test passes at repair head; retained live report records exact pair and rejection replay.
- ✅ VERIFIED: One-file Box AI table extraction, pinned AWS-hosted Haiku within Box, supporting quotes, regional GLM fallback.
  - Evidence: kloop/extract/provider.py; test_box_sdk_pinned_table_content_and_pacing, test_box_api_error_falls_back_but_invalid_payload_does_not, test_glm_regional_fallback_uses_pinned_model_and_complete_json.
  - Verification: offline SDK request/response and fallback assertions pass; no direct Bedrock Claude dependency. Provider is unchanged by repair.
- ✅ VERIFIED: Automatic quote/required-field/procedure checks, duplicate/conflict checks, review actions and off/exceptions/all modes.
  - Evidence: service.py and tests for automatic_checks, duplicate_and_cross_source_conflict, edit_and_persistent_review_mode, approve_change_retire_and_immutable_snapshot.
  - Verification: focused suite passes for memory and moto repositories. Original defect is fixed at service.py:245-250: pending upsert approve/edit fails while the source is deleted. Eight new cases cover initial pending items and new pending attributes beside approved items, approve/edit, unchanged state on refusal, rejection/idempotence and restoration.
- ✅ VERIFIED: Stable item/attribute identity, source-version provenance, separate decisions/effective status and immutable approved snapshot hashes.
  - Evidence: canonical schemas; service._identity/_apply/snapshot; repository snapshot conditional writes; stable_supplied_identity and immutable_snapshot tests.
  - Verification: focused tests pass; original approved snapshots survive subsequent changes and corrupt hashes are rejected.
- ✅ VERIFIED: Omission never retires; explicit/deleted-source retirement and restored-source behavior; durable idempotent process/retire preserving rejections.
  - Evidence: sync Protocol, ExtractionService and DynamoRepository CAS; omission, explicit_retirement, restored_same_version, rejected_semantics, ambiguous_success_replay, superseded_review and new deleted-source tests.
  - Verification: all relevant memory/moto tests pass. Runtime factory uses existing CCG and named items table. No new requirement or scope expansion.

### Evidence index
- Commits reviewed: 4e9035f, 696c1db; tested complete committed tree 696c1db.
- Notes reviewed: task 631555a7-e757-4b6b-a82a-6460b253bbfc; Spec Decisions/Acceptance Criteria; PR Context 846fb942-136d-4b81-98f2-354a4926f1de and repair handoff.
- Areas: kloop/extract/*, shared extraction schemas, tests/test_extract.py, recorded fixtures, frozen pack and saved live evidence.
- Verified in a git archive of the exact pushed commit under task-owned /tmp, excluding concurrent uncommitted medical/training work.

### Tests/Commands Run
- Credential-free `uv run --locked pytest tests/test_extract.py` → PASS, 47 tests.
- Credential-free `make test && make lint` → PASS, 288 tests; Ruff check and format pass (75 files).
- `git diff --check 7e68a5b 696c1db` → PASS.
- `git ls-remote origin refs/heads/withered-cobra` → repair SHA matches pushed branch at verification start.
- Independent saved-evidence audit → PASS: original extraction code hashes and frozen pack hashes matched before repair, recovery recomputed 13/13, 14 raw responses and all ledger rows recorded cleaned.
- Credential-free environment removed AWS/BOX/KLOOP and secret/token/credential/password/private-key variables; AWS_CONFIG_FILE, AWS_SHARED_CREDENTIALS_FILE and BOTO_CONFIG=/dev/null; AWS_EC2_METADATA_DISABLED=true.
- `make extract-live` intentionally NOT rerun under the no-spend instruction. Retained live proof is historical at original extraction implementation; repair is supported by independent offline regressions.

### Risk Notes
- No new live AWS/Box calls, resources, product edits or spend. This approves the extraction task only; deployed wiring/webhook timing and unrelated tasks are not certified.
- Original saved live evidence predates the six-line review guard; provider/scorer unchanged. Full tests replay its frozen corpus at repair head. One dependency deprecation warning from Starlette/httpx; no failures.
- No spec ambiguity blocked approval.
