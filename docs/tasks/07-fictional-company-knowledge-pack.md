# Fictional company knowledge pack

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `9fcb8ca7-3f25-4063-89ac-6b6c75ed17a1`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

The Halvard Systems documents, gold items, question sets and the v2 edit used in the demo.

## Scope
`pack/`: start from the POC 2 mini pack (`poc/company-knowledge`) and its sealed hidden set (46 + 6 procedure addendum). Grow to 8–12 facts and 3–4 procedures across 4–6 documents (docx or md). Include the E42 pair: the fact "E42 on the X200 means the fan failed" and the procedure "E42 with high temperature: check airflow before replacing the fan". Gold items as JSON. Questions: train seeds, a **dev set** (for the gate) and the **sealed hidden set** (reuse POC 2's; add new hidden questions only for new facts, sealed with a new hash; never edit sealed ones). The v2 edit: one changed limit (Dana's approval $7k → new value) and one retired product (Atlas). Rewrite the demo scenarios for LoRA (scenario 5 gives the held-out rule in the question). Manifest with hashes.
Not in scope: code beyond a small validator.

## Definition of Done
Validator checks: every gold item quotes its document; no hidden question overlaps train/dev (same overlap audit as POC 2); hashes match the manifest.

## Verification
`make test` (validator); `make pack-check`.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Freeze the POC 2 corpus as is**: keep `poc/company-knowledge/pack.json` semantics exactly (E42 = pump / inlet pressure as tested). No new X200 fan rule, no Dana/$7k, no Atlas, no pack expansion. The sealed hidden set (46 + 6) and its hashes stay unchanged.
- **The v2 edit uses existing items:** pick one existing fact whose value changes and one existing item that is retired; add version-specific dev/hidden probes for both (sealed with a new addendum hash, disclosed as added after training-data generation).
- Documents in **MD/TXT only** (no DOCX).
- Rewrite the demo scenarios against this pack (E42 contrast uses the POC's pump rule).
- DoD adds: a manifest tying corpus, question sets, prompt and hashes together; the validator confirms the pack is byte-identical to the POC 2 version except for the v2 files.

## Implementation checkpoint

Read the full approved override: POC 2 semantics and sealed 46+6 remain frozen. Owning pack/, tests/test_pack.py, and only the Makefile pack-check target. Coordinated with the model-experiment agent: reference its dev set only after committed, otherwise expose a pending slot. Planned v2: F06 Sable 73 GB → 96 GB, F10 Quartz recovery guidance retired. No AWS or Box resource mutations.

## Completed implementation and verification

Completed at 2026-10-17T07:06:12Z on withered-cobra. Base d59d505016c933fe32b95e67afad2cb7db1e24f6; task head 2d9203851b4ed045d928fe320d0ac9ff59aa8ec3. No PR (not requested); no push attempted because another agent has tracked work in progress. Coordinator should pull --rebase before the eventual push once shared edits are committed.

Added pack/: byte-identical POC 2 pack, original sealed 46+6 and freeze evidence; 13 TXT source documents matching Box seed output; quoted gold items; common system prompt; manifest; frozen 386-row training-seed reference; separate v2 corpus/documents/gold/change ledger. V2 changes only F06 Sable 73→96 GB and retires F10 Quartz recovery guidance. Added four dev and four separately sealed hidden version/item probes. New hidden SHA256 f476ddb5383d91d7915560e202c7b444ef92c066b72a5ab0d5d2f971aecb19ee. Seal explicitly discloses post-original-training-data creation and separates v1/v2 scoring. Manifest SHA256 aec0dda2bdb95d64713eb53eceedf2b24c7409013ef4723f7692606a2e625f27.

Added read-only pack/validate.py and tests/test_pack.py plus Makefile pack-check target. Validator checks immutable POC anchors and byte identity, source quotations and document inventories, approved v2 changes, file hashes, question counts, common prompt, and the POC 2 0.78 lexical overlap audit for train/dev versus original and new hidden questions. Tests verify rejection of resealed original-corpus edits, unsupported quotes, unauthorized v2 changes, and normalized overlaps.

Rewrote the existing demo-scenarios note 65bb0a42-08ed-4a4c-b9fc-e51c4930bc40 and pack/demo-scenarios.json for phase 1 LoRA: existing facts, honest composition check, E42 pump rule, fully supplied unfamiliar rule in scenario 5, disclosed pre-trained v2 switch, and unsupported-question abstention. No claims of guaranteed learning or forgetting.

Verification: make pack-check PASS; make test PASS, 117 tests including parallel agent sync tests at that moment; ruff check/format for pack validator and tests PASS; git diff --check PASS. No live AWS/Box calls, training, model inference, or resources created. No known base CI failure or CI run link was established; no CI/PR run requested.

Authorized pending slot: the model experiment had not committed its shared dev set at handoff. Manifest references status=pending/gate_ready=false; no duplicate set created. Coordinator should insert its committed path/hash when available, then rerun pack-check. Structural pack validation passing is not a promotion-gate or runtime-learning claim. Files touched: pack/**, tests/test_pack.py, Makefile only; AGENTS.md/CLAUDE.md and other agents’ files excluded. Shared branch was retained to avoid changing other agents’ checkout.


## Dev set (frozen 2026-10-17)
The dev set is `poc/model-experiment/data/dev.jsonl` (30 questions, 8 untold), SHA256 `5773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf`, commit 02d0857, audited against the hidden set, the addendum, the 386 training rows and itself. Reference it by path and hash; don't copy or edit it.

## Verifier findings — fictional knowledge pack, 2026-10-17

### Verification Summary
- Verdict: ❌ NOT APPROVED for the requested combined verification gates.
- Confidence: High.
- Pack-specific criteria all pass. Required credential-free full-suite gate fails in another task's test isolation; coordinator must resolve it before full approval. No pack implementation defect or spec ambiguity found.
- Task commit: 2d9203851b4ed045d928fe320d0ac9ff59aa8ec3, base d59d505016c933fe32b95e67afad2cb7db1e24f6. Normal and credential-free full-suite runs started at shared head 142e8ae0a78e1bdf6bad5b2cc8735ebd33698f4b. Concurrent model-only commit advanced head to 02d0857b61a758b4586dc2c3958294107fa5f66b; git diff 2d92038 HEAD -- pack tests/test_pack.py is empty.

### Acceptance Criteria Checklist
- ✅ VERIFIED: Frozen POC 2 corpus and sealed 46+6 unchanged; no expansion or Dana/Atlas/X200 content.
  - Evidence: pack/pack.json and six copied corpus/sealed artifacts independently byte-compared to poc/company-knowledge; exact corpus hash b4d7aef08e0dbb39c3007c317648e964ff5ff8f388a44c7e87a71755589c4320; original hidden aceed4dbde268e7f1a22cd6fcf99772a2e8b229e2dbe16645f97ba2a78ebb8ee; original procedure addendum f8765dbf47a1cc5c12a93fa6be81e1e6ec737206cfb6fc6bf46d5ace37ad4457.
  - Verification: independent Python byte/hash scan; validator immutable anchors; forbidden-content scan passed.
- ✅ VERIFIED: Every gold item quotes its document; MD/TXT source documents only.
  - Evidence: pack/gold.json, pack/v2/gold.json and both documents directories, 13 TXT documents per version.
  - Verification: independently checked all 26 supporting quotes against source text; validator checks exact statement/document equality and inventories.
- ✅ VERIFIED: V2 changes only existing F06 73→96 GB and retires F10, with version-specific dev/hidden probes and new seal.
  - Evidence: v2/pack.json, changes.json, gold.json, dev.jsonl and sealed/{hidden.jsonl,manifest.json}. Four dev and four hidden probes cover both items in both versions. New hidden hash f476ddb5383d91d7915560e202c7b444ef92c066b72a5ab0d5d2f971aecb19ee.
  - Verification: reviewed all eight answers and retirement semantics; validator exact v2 comparison and probe inventory pass. Seal explicitly discloses creation after original data generation and separate version scoring.
- ✅ VERIFIED: Manifest binds corpus, questions, prompt and hashes; POC overlap audit is preserved.
  - Evidence: manifest.json; validate.py uses normalized SequenceMatcher/Jaccard maximum with 0.78 rejection threshold; frozen 386-row training reference and common prompt.
  - Verification: make pack-check passes hashes, inventories and train/dev versus original/new hidden overlap checks. Five pack tests include adversarial resealing, unsupported quotes, unauthorized v2 changes and normalized-overlap rejection. Shared dev slot remains pending/gate_ready=false, explicitly accepted by assignment even though model agent has now committed its set.
- ✅ VERIFIED: LoRA demo scenarios use pump/inlet pressure and provide the unfamiliar rule in scenario 5.
  - Evidence: pack/demo-scenarios.json and rewritten demo-scenarios note 65bb0a42-08ed-4a4c-b9fc-e51c4930bc40.
  - Verification: read all six scenarios; v2 switch is disclosed as pre-trained, source labels are lineage, no guaranteed learning/forgetting claim.
- ✅ VERIFIED: Scope, small validator, no secrets or cross-task edits.
  - Evidence: exact task commit has 45 paths: pack/**, tests/test_pack.py, Makefile only. Makefile diff adds only pack-check.
  - Verification: reviewed task code/data and bounded credential-pattern scan across all changed committed paths: zero findings. git diff --check passes. Verification made no repository edits or live service calls; concurrent untracked model artifacts and AGENTS.md/CLAUDE.md untouched.
- ⚠️ DEVIATION: Spec “make test passes without AWS or Box credentials” / assigned credential-free make test && make lint.
  - What differs: credential-free full suite returns 1 failed, 107 passed, 19 errors; sync tests raise ProfileNotFound: box-hackathon. Chained lint does not execute after failure; separately run credential-free lint passes.
  - Impact: fresh projects cannot run the complete advertised offline suite.
  - Evidence: tests/test_infra_commands.py:test_destroy_does_not_delete_table_if_creator_is_pending invokes scripts.infra.main; scripts/infra.py:64 sets os.environ["AWS_PROFILE"] without this test restoring it. Subsequent boto3.Session fixture in tests/conftest.py inherits the missing profile. Two-test reproduction gives 1 passed, 1 error. This is outside the pack task; not claimed pre-existing on the supplied base because base CI was not checked.
  - Suggested minimal fix: owner restores environment changes in the infrastructure test or isolates main invocation; avoid changing the pack. Coordinator should route/reopen the responsible task. Pack task was already complete and verifier has not attempted to reopen it.
  - Re-verify: credential-free two-test reproduction, then credential-free full make test && make lint, normal make test && make lint, make pack-check.

### Evidence index
- Commit: 2d9203851b4ed045d928fe320d0ac9ff59aa8ec3.
- Notes: full PR context 846fb942-136d-4b81-98f2-354a4926f1de, full pack task 9fcb8ca7-3f25-4063-89ac-6b6c75ed17a1 including overrides/later handoff, spec, demo-scenarios note.
- Areas: all 45 task paths; original frozen files/training reference; infra test/environment lines used to explain failed gate.

### Tests/Commands Run
- make test && make lint → PASS: 127 tests, Ruff check and 38 files formatted.
- Same chain with every AWS_*, BOX_* and KLOOP_BOX_* environment variable removed, AWS_CONFIG_FILE=/dev/null, AWS_SHARED_CREDENTIALS_FILE=/dev/null and metadata disabled → FAIL: 1 failed, 107 passed, 19 errors.
- Credential-free make pack-check → PASS; pytest -q tests/test_pack.py → PASS, 5 tests; make lint → PASS.
- Credential-free pytest -q --tb=line tests/test_infra_commands.py::test_destroy_does_not_delete_table_if_creator_is_pending tests/test_sync.py::test_duplicate_body_event_is_enqueued_once → reproduced missing profile, 1 passed/1 error.
- Scoped Ruff check/format including pack/validate.py → PASS (root Ruff configuration otherwise excludes pack/).
- git diff --check 2d92038^ 2d92038 → PASS.
- Independent corpus bytes/hashes, 26 quotes, document extensions, forbidden-content and changed-file credential-pattern scans → PASS.

### Exact re-verify commands
Run normal: make test && make lint && make pack-check.
For credential-free verification use:
```sh
python3 - <<'PY'
import os, subprocess
env = {k:v for k,v in os.environ.items() if not k.startswith(("AWS_", "BOX_", "KLOOP_BOX_"))}
env.update(AWS_CONFIG_FILE="/dev/null", AWS_SHARED_CREDENTIALS_FILE="/dev/null",
           AWS_EC2_METADATA_DISABLED="true", BOTO_CONFIG="/dev/null")
raise SystemExit(subprocess.run(["sh", "-c", "make test && make lint && make pack-check"], env=env).returncode)
PY
```

### Risk Notes
Only local pack integrity/isolation is verified. Lexical isolation cannot prove semantic separation; previously viewed hidden scores remain exploratory. Pending shared dev wiring is accepted and still blocks promotion. No AWS/Box runtime, training quality or deployment acceptance is claimed.



## Coordinator acceptance (2026-10-17)
The pack verifier passed every pack criterion and blocked only on the shared credential-free test failure (an environment leak from an infra test). That was fixed in b382cd5 and re-verified by the sync verifier at fc54528: the full suite of 127 tests passes credential-free. Pack accepted as complete.
