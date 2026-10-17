# Model experiment: Bedrock re-import, abstention data, 4B vs 8B

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `cb30a48b-d131-4c6f-a5a9-6faf5db71a94`. Task status: **waiting**. Earlier progress entries are historical; later dated entries record updates.

Decide the phase 1 model and training recipe with evidence: fix the LoRA's overconfidence (POC 2 said "I don't know" only 2/10 times) and test whether Qwen3-8B does better than 4B. Also settle why the POC 2 trained import never starts in Bedrock.

## Scope
**A. Bedrock re-import (start immediately, in parallel).** Re-import the exact POC 2 merged weights (s3://box-hackathon-poc2-s17-20261017-549803795565/training/seed17/merged/) once into the free 3rd slot, with the same settings and a new name. Run the bounded cold-start test (~10 min). If it serves: report "one-off failure", then delete the broken import x2feesmws1lw (approved). If it also never serves, report the weights or this path as the suspect, keep both for diagnosis, and don't import anything else until the coordinator decides. Record both outcomes in the ledger.

**B. Better data (abstention).** Build training data v2 from the frozen POC 2 pack: keep the 386 approved rows and add plenty of **"I don't know" cases** (Halvard-sounding questions the documents don't answer, about 25–30% of rows) and **near misses** (wrong product, person or value: answer with the correct item or decline). Kimi K3 writes them, GLM-5 checks them, then dedupe and the same strict overlap audit against the sealed hidden set (the builder never reads hidden answers; use the audit tool only). Commit with hashes.

**C. Dev set for decisions.** Create a small **dev set** (~30 questions across all kinds, including ~8 untold) that is separate from training and from the sealed hidden set, and audit it the same way. Choose configurations on the dev set only. Report hidden-set scores too, labelled exploratory (the hidden set has been viewed).

**D. Train and compare (SageMaker, no Bedrock slots needed).** Train two LoRAs on data v2 with the POC 2 settings (seed 17, 3 epochs, LR 2e-4, max length 512 with the truncation guard): (1) **Qwen3-4B-Instruct-2507**; (2) **Qwen3-8B** (instruct/chat version from JumpStart; check the license and that Bedrock Custom Model Import supports it; mirror it to S3; use gradient checkpointing; QLoRA only if bf16 LoRA doesn't fit in 24 GB). Use ml.g5.2xlarge and ml.g6.2xlarge in parallel (1 each). Evaluate each with the evaluation-only SageMaker job (POC 2's fallback, greedy, max 256 tokens, the same prompt) on the dev set and the 52 hidden questions, scored by blinded GLM-5. Also run base 8B (without and with search) on the dev set for a fair comparison.
Report a table: base / search / LoRA for 4B and 8B, by question type, with paired raw counts, plus training cost and time. Recommend 4B or 8B and the data recipe for phase 1, considering Bedrock import size and cost (CMUs) and cold start.
"Larger than 8B" (for example Qwen3-14B) is out of scope unless 8B clearly helps; then estimate GPU memory and quota needs, and don't request quota.

## Definition of Done
A results note with the table and recommendation; data v2 and the dev set committed with hashes; the re-import outcome recorded; temporary roles and logs cleaned up; at most 3 imports exist.

## Verification
The results note, commits, and a final `list-imported-models` census in the report.

## Rules
Branch withered-cobra, code under poc/model-experiment/ (reuse poc/company-knowledge and poc/sagemaker-bedrock without changing them). Total spend for this task ≤ $10; stop and report before anything bigger. No Support or quota requests. No rm outside /tmp. No Claude attribution.

## Started 2026-10-17T07:05Z
Read spec, task scope, POC handoffs, and active-agent census. Files restricted to poc/model-experiment/; other agents own pack/ and sync work. AWS profile box-hackathon identity verified, selected Region us-east-2, plan FREE/ACTIVE with $120 remaining credits. Starting exact re-import first. No resources created yet.

## Running — 2026-10-17T07:10Z
Exact POC2 re-import submitted as job c4z39hz07w41 (same S3 prefix/config/tokenizer; new name box-hackathon-experiment-reimport-20261017), third slot only. Scoped temporary role recorded in poc/model-experiment/evidence/reimport.json. One-hour terminal-status watcher; cold test follows completion.
Kimi K3 training additions (180 candidate untold + 60 near misses) and independent dev candidates are generating in parallel. Target final data: original386 preserved +130 unknown +40 near misses =556 rows,157 unknown (~28.2%). GLM-5 review and strict0.78 hidden+addendum/train-dev overlap audit must pass before training. No hidden inputs enter builder/reviewer.
Pinned JumpStart Qwen3-8B catalog version3.15.0; artifact inference-prepack/v3.0.0, Apache2.0, not gated, Qwen3ForCausalLM supported by current Bedrock import docs. AWS-only mirror running to task-owned tagged encrypted private bucket box-hackathon-experiment-20261017-549803795565. No laptop weight downloads. No SageMaker jobs submitted yet.
Controls commit1a11c7cf6b977e27f4496df7a89e4bc55dc58de8; python3 -m py_compile poc/model-experiment/*.py PASS; scoped git diff --check PASS. Training caps planned2400s/job and eval1800s/job; g5/g6 one each; no endpoints or new quotas. Four one-hour watchers cover import, train generation, dev generation and mirror. Next wake: review completed datasets, freeze/audit, then submit paired training jobs. All conclusions pending.

## Coordinator amendments received
If8B clearly beats4B on dev, add14B estimates only: Bedrock import support, expected CMUs/per5min cost, import/cold timing, bf16 LoRA vs QLoRA memory, fitting SageMaker instances and read-only applied quotas. No14B training or quota request.
Pack commit2d9203851b4ed045d928fe320d0ac9ff59aa8ec3 awaits the committed shared dev path/hash. Pack v2 changes F06 Sable73→96GB and retiresF10 Quartz; separate from this data-v2 recipe. Keep all pack/v2/sealed inputs out of builders. Send coordinator final dev path/hash to replace pending manifest reference.

## Dev generation completed — 2026-10-17T07:08:53Z
Kimi generated58 dev candidates:14fact,6two-fact,8procedure,6near-miss,16unknown,8general. GLM-5 semantic review started; one-hour review watcher replaces retired generation watcher. Final30 selection still waits for semantic review and hidden/train overlap audit. Official current Ohio training price evidence saved to evidence/training-prices.json; no GPU jobs yet.

## Frozen shared dev handoff — 2026-10-17T07:11Z
Task cb30a48b-d131-4c6f-a5a9-6faf5db71a94. Dev commit02d0857b61a758b4586dc2c3958294107fa5f66b; path poc/model-experiment/data/dev.jsonl; SHA2565773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf. Thirty questions:8fact,3two-fact,4procedure,3near-miss,8unknown,4general. Kimi generated58 candidates and GLM-5 accepted58; selected30 pass strict0.78 hidden+addendum/original386/dev duplicate audit. Frozen against original386; subsequent training additions must avoid frozen dev. Original386 also re-audited successfully against hidden+addendum. Checks: audit_data.py --dev-only PASS; py_compile PASS; scoped diff --check PASS. PR URL/number not created by this task; base SHA d59d505016c933fe32b95e67afad2cb7db1e24f6, task head02d0857b61a758b4586dc2c3958294107fa5f66b. No repo CI or base-failure CI link. Files: audit_data.py, data/dev.jsonl, data/dev-manifest.json and data/dev/* provenance.

## 8B mirror ready — 2026-10-17T07:12Z
Mirrored16,397,448,209bytes directly within Ohio; completed07:11:04Z. Context32K configSHA256055a72c06ee56169e33d23d1639a414c073a0a8e838248adb25bfc1c9ce66c14; licenseSHA256832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e. Provenance committedfc54528b717ff395977181c76b2c53f42a9a1a8b.
Live Ohio rates pinned:$1.515/hr g5.2xlarge training,$1.222/hr g6.2xlarge training. Budget guard now runs before further model calls and job launches. At07:12:30Z known helper estimate$0.95824; conservative total reservation$9.15140 including all four GPU runtime caps, future helper reserve$3, Bedrock reserve$1.50 and storage/logs reserve$0.50. Not a final bill. No SageMaker jobs yet; training generation and exact re-import watchers remain armed. Syntax and scoped diff checks PASS.

## Generation timeout recovery — 2026-10-17T07:16Z
All nine unknown batches are cached. First near-miss call hit the AWS CLI read timeout; no credential error. Preserved original failure log in evidence/generation-timeout.log. Resumed using exact cache request hashes, with180s CLI read timeout and10s connect timeout; only uncached requests invoke Kimi again. New one-hour watcher968d6307-9f8a-4f79-95cc-d8c070edc24d. Timed-out request may have incurred unreported tokens; remaining helper reserve covers this uncertainty. No GPU training or new import submitted.

## Exact re-import completed — 2026-10-17T07:16:16Z
Jobc4z39hz07w41 created07:03:56.219Z, ended07:15:20.178Z (683.959seconds). Imported ARN arn:aws:bedrock:us-east-2:549803795565:imported-model/ol1fd5dnxm6w. GetImportedModel confirmsqwen3,1CMU/copyv1.0,instructSupported=false, exact unchanged POC2 S3 source. Ten-minute cold probe started07:16:27Z; first request ModelNotReadyException.60s cadence with20minTTL (longer than bounded test). No serving success claimed yet and old import remains retained.

## Coordinator slot/deadline amendment — 2026-10-17T07:17:43Z
After the bounded cold-start test finishes, delete exact old importx2feesmws1lw regardless of outcome; new importol1fd5dnxm6w preserves identical weights. This supersedes the original keep-both-if-fail rule. Retain base0inmdc8ttj1w and re-importol1fd5dnxm6w only; do not import4B/8B experiment candidates. Evaluate both through SageMaker-only jobs. Report re-import result immediately when known. If dev comparison unfinished by09:00UTC, report partial evidence; coordinator will lock4B.

## Part A complete — 2026-10-17T07:20Z
**One-off failure:** exact POC2 weights re-imported successfully and returnedREADY on attempt4. New ARN arn:aws:bedrock:us-east-2:549803795565:imported-model/ol1fd5dnxm6w. Service import683.959s; observed startup184.589093s including retry gaps; successful request0.762073s,26prompt/2outputtokens.1CMU/copyv1.0. This proves the same POC2 weights can serve; it does not establish the original failure root cause.
Deleted approved oldx2feesmws1lw at07:19:50.834669Z and own import role at07:19:52.552751Z. Fresh census exactly2imports: base0inmdc8ttj1w and re-importol1fd5dnxm6w. No experiment candidate import. Evidence sealed commit6b1448cf5cf85b0dc04d3b9b4e5f3c4aec5e17e0 under poc/model-experiment/evidence/{reimport,reimport-model,cold-runtime,reimport-outcome}.json. Python syntax/scoped diff gates PASS. PR URL/number not created by this task; no base-CI failure assessment. Files in commit limited to own model-experiment controls/evidence.

## Training generation complete — 2026-10-17T07:21:07Z
All240 candidate additions generated:180unknown+60near-miss. One read-timeout recovered by reusing caches and retrying uncached batch with180s timeout. GLM-5 review started for240rows, one-hour watcher8bb0a931-68e9-48c7-8731-4d599d032342. Final selection remains130unknown+40near-miss subject to semantic acceptance, dedupe, hidden+addendum audit and separation from frozen dev. No GPU jobs submitted yet.

## Training data frozen — 2026-10-17T07:25Z
Data commit82083ae9202bb257a23b71024fee60d01740dcd2. train-v2.jsonl SHA256ea7f4acc251974a35223326b3733c0e61b59d956a1c8e459db21705cc7e76af0,556rows:179fact,60procedure,157unknown(28.2%),64near-miss,96general. All original386 preserved exactly as rows. Kimi generated240additions, GLM-5 accepted240, final deterministic selection130unknown+40near-miss. Strict0.78 hidden+addendum/dev/duplicate audit PASS; no collisions among selected rows. Dev remains unchanged SHA2565773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf. Inference-only evaluation manifest has30dev+52hidden prompts, SHA2561c97dc1ff41e57fbfa666e0786b64f556238fc4b89009e6a3dabe7efd2fc368e.
Gates: audit_data.py PASS, prepare_evaluation.py PASS, Python syntax/scoped diff PASS. Initial train4 submission rejected before job creation because new role could not yet be assumed; role trust verified correct, no job exists in fresh census. Retrying once after propagation; train8 role preparation separated from submission. Budget conservative reservation$9.63858 before GPU submission; no credentials error. Files only under poc/model-experiment/data plus owned job control state. PR URL/number not created by task; no repo/base CI assessment.

## Parallel training submitted — 2026-10-17T07:27Z
4B job box-hackathon-experiment-train4-20261017 on1×ml.g5.2xlarge;8B job box-hackathon-experiment-train8-20261017 on1×ml.g6.2xlarge. Both fresh statusInProgress/Pending. Seed17,3epochs,LR2e-4,rank16/alpha32 q_proj+v_proj, accumulation4,bf16, gradient checkpointing; max length512 with unchanged POC2 truncation guard (raises limit to1024 if needed and rejects truncation). MaxRuntime2400s and MaxPending1800s each. Digest-pinned POC2 image/dependencies; no endpoints or Bedrock candidate imports.
Training requests/roles/control hashes committedafbd0b678ca9d368c64834435fc30e6b26f20502. Data remains commit82083ae9, trainSHAea7f4acc251974a35223326b3733c0e61b59d956a1c8e459db21705cc7e76af0. New90min job watchers exceed pending+runtime limits;09:00UTC deadline remains armed. First4B submission role-propagation rejection recovered after read-only absence/trust checks; exactly one job of each name exists.
Files: jobs.py,budget.py,evidence/{train4,train8,budget}.json. Python syntax/scoped diff gatesPASS. PR URL/number not created by this task; no repo-wide CI or base-failure CI link. Next: download training reports, run separate evaluation-only jobs for base/search dev and LoRA dev+52hidden, then blinded GLM-5 scoring.

## 4B training completed — 2026-10-17T07:42Z
SageMaker Completed:831billable seconds (~$0.3497125 at pinned Ohio rate). Report:556rows,3epochs,417optimizersteps,seed17,LR2e-4,max_length512; maximum184tokens,0truncation. LoRA training538.776973s,merge27.626881s,upload/hash39.689233s,CUDA peak8,822,848,512bytes. Data and control SHA reverified against submitted request; report fields/settings match. Full merged15file hashes retained in evidence/train4-report.json.
Prepared separate evaluation-only jobeval4 (base/search on30dev, merged LoRA on30dev+52hidden; greedy max256), including candidate hash validation. Role preparation precedes delayed submission to avoid IAM propagation race.90min evaluation hook armed;8B training and09:00checkpoint watches continue. No Bedrock candidate import.

## 8B training completed — 2026-10-17T07:43Z
SageMaker Completed:826billable seconds (~$0.28038111 at pinned Ohio rate). Report:556rows,3epochs,417steps,seed17,LR2e-4,max_length512; maximum188tokens,0truncation. BF16 LoRA fit on24GB GPU; peak16,924,554,752bytes, noQLoRA needed. Training475.338538s,merge64.362450s,upload/hash70.433923s. Exact data/control hashes and settings reverified.
8B evidence/evaluation inputs committed9f11f5bfcfb68e929fa9648a4ea58df645a82cae;4B evidence committed5f0607528b59929766dbcd1c2689d08f7515337a. Both separate eval-only jobs prepared with candidate-file hashes,30dev base/search plus30dev+52hidden LoRA per size, greedy max256/non-thinking templates.90min evaluation watchers and09:00deadline armed. Combined GPU training estimate$0.63009361; final invoice not yet available.
Files: evidence/train8.json,train8-report.json,eval8.json,budget.json,data/evaluation8.json. Gates settings/data/script hash checksPASS. No app CI/base-failure CI link; no PR created by task. Decision and conditional14B estimate wait for dev scores; hidden scores remain exploratory.
