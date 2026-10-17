> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `5a1c7717-8e36-4a90-8e08-57764fb92cff`. Earlier progress entries are historical; later dated entries record updates.

## Final result — ADJUST phase 1

The small LoRA recalled the invented single facts in new wording, but it was unreliable on combined facts and unknown company details. Use search as the authoritative knowledge source for phase 1. Do not ship this LoRA as the sole factual source or claim that its Bedrock serving path passed.

**LoRA results below were served via SageMaker/transformers, not Bedrock.** The base and search results were served via Bedrock. This runtime difference is a confound; there is no matched transformers base control, so the observed gain cannot be attributed solely to LoRA.

| Question type | Base — Bedrock | Base + search — Bedrock | LoRA — SageMaker/transformers, not Bedrock |
|---|---:|---:|---:|
| Single facts, new wording | 0/20 | 19/20 | 20/20 |
| Two facts together | 0/5 | 5/5 | 1/5 |
| Procedures | 2/7 | 6/7 | 6/7 |
| Untold details: correct abstention | 10/10 | 10/10 | 2/10 |
| Unrelated questions | 10/10 | 9/10 | 10/10 |
| Total correct | 22/52 | 49/52 | 39/52 |
| Invented answers on untold details | 0/10 | 0/10 | 8/10 |

These are raw GLM-5 judgments, not audited accuracy estimates. All 52 LoRA responses stopped normally, without hitting the 256-token cap. The procedure subset contains one supplied-rule transfer question (1/1 for all three modes) and six new situations from the three trained rule families (base 1/6, search 5/6, LoRA 5/6).

Manual review found likely overcredit: LoRA A03 does not actually state the supply-restoration/retest steps that GLM claims it does; A06 gives an incorrect temperature threshold despite choosing the correct action for that situation. A04 is contradictory and was correctly marked wrong. The search baseline's A03 also has contradictory prose despite a raw pass. Scores were preserved without post-hoc overrides or reruns; inspect [manual review](intent://local/file/poc/company-knowledge/evidence/manual-score-review.json). The procedure result does not establish safe troubleshooting behavior.

No unrelated-question regression was observed for this LoRA on these ten questions. Its eight invented unknown details are the decisive regression: examples include an invented administrator password, sensor price, office address and replacement part. Single-fact recall is encouraging, but multi-fact composition and abstention are inadequate. This is one seed and a small exploratory set.

## Execution and evidence

Qwen3-4B-Instruct-2507, 32K context; 386 Kimi K3 examples independently reviewed by GLM-5 and filtered for duplicates/hidden overlap. LoRA r16/alpha32 on q_proj/v_proj; seed17, configured 3 epochs, LR2e-4, length512, gradient accumulation4. Actual trainer result: 288 steps, epoch2.974093; training334s, merge24s. All386 examples were scanned; maximum184 tokens, zero truncated. No examples were dropped by the truncation guard. No second seed was run.

Training and the single approved evaluation-only job both completed on on-demand ml.g6.2xlarge, each capped at3600seconds. Evaluation loaded the exact merged files and verified every file's size/SHA against the training report before inference. It used the same cached52 baseline prompts and Qwen chat template, greedy decoding (temperature0), max256 new tokens. Generation took50.117s. GLM-5 used the same rubric and batching as the baseline, with no judge fallback.

SageMaker billable time: training590s + evaluation254s. At the recorded Ohio price $1.222/hour, compute estimate is **$0.286491**, excluding storage, logs and all Bedrock generation/judging/import/inference charges; this is not an AWS bill. Final LoRA judging used6836 input/2835 output tokens. Earlier Kimi generation estimate was$0.6920364. No action exceeded the approved$10 expected-spend cap.

Frozen hashes:

- Original46 hidden questions, sealed before any generation: `aceed4dbde268e7f1a22cd6fcf99772a2e8b229e2dbe16645f97ba2a78ebb8ee`.
- Six-question v2 addendum, sealed after data generation but before LoRA: `f8765dbf47a1cc5c12a93fa6be81e1e6ec737206cfb6fc6bf46d5ace37ad4457`.
- Final386-row training set: `92edb882d2233b7604b2072abe98c46d81dced97b0a54356788f160dddac1a72`.
- Dataset manifest: `e2f7acfa96c583af99fb4fae7a045b626cabbf9ee380cedfdfe81da4278ec806`.
- [Final comparison](intent://local/file/poc/company-knowledge/evaluation/final-comparison.json): `3afe7c09aaa452f617c0beb2e10ee5091cd7a169b1a93b355b2d53532a56e46a`.

Original and addendum bytes, pack and training data remained unchanged. The strict0.78 lexical overlap audit passed; it does not prove semantic disjointness. The addendum tests new situations in seen rule families, not unseen procedure families.

## Bedrock runtime and tokenizer diagnosis

Candidate `arn:aws:bedrock:us-east-2:549803795565:imported-model/x2feesmws1lw` imported in about604s but returned ModelNotReadyException on all11 bounded readiness calls over ten minutes. There was zero successful Bedrock candidate response. The independently reported answer-library smoke also failed. The fallback proves transformers inference on the merged weights, not Bedrock acceptance.

Read-only comparison with POC1's tiny merged model, which did serve, found identical config, generation configuration, tokenizer configuration, chat-template, added-token and special-token-map hashes. The training reports also show identical tokenizer.json, merges.txt and vocab.json hashes. Both merged folders have the same extra/absent tokenizer-related files. The chat template is present and unchanged. **Copying base tokenizer/generation files is therefore not a likely fix supported by these differences.** The underlying runtime cause remains unknown. No files were changed and no re-import, Support case or quota request was made.

## Resources and cleanup

Per the coordinator's explicit decision, KEEP candidate x2feesmws1lw and its source artifacts pending the demo decision. Retained own bucket: `s3://box-hackathon-poc2-s17-20261017-549803795565/`; source `training/seed17/merged/`, adapter/report and evaluation evidence are retained. Shared base0inmdc8ttj1w was untouched. No endpoints were created.

Deleted and independently verified absent: own training role, import role, evaluation role, their inline policies, four temporary control objects, and the newly POC2-created empty training log group. [Cleanup verification](intent://local/file/poc/company-knowledge/evidence/cleanup-verification.json) confirms the tagged candidate remains. SageMaker completed-job records remain as history, not running compute.

## Commands and verification

Commands use AWS_PROFILE=box-hackathon and AWS_REGION=us-east-2.

Training was launched with `python3 poc/company-knowledge/training_job.py launch --state /tmp/box-hackathon-poc2-s17-state.json`; exact submitted request is [training submission](intent://local/file/poc/company-knowledge/evidence/seed17-training-submission.json). The approved single evaluation-only job used `python3 poc/company-knowledge/eval_job.py launch --state /tmp/box-hackathon-poc2-eval-state.json`; its request is [evaluation submission](intent://local/file/poc/company-knowledge/evidence/seed17-evaluation-submission.json).

Scoring used `evaluate.py --lora --sagemaker-responses poc/company-knowledge/evidence/seed17-sagemaker-responses.json`, candidate ARN x2feesmws1lw, merged tokenizer/config files and their recorded expected hashes, output directory `evaluation/lora-seed17-sagemaker/`. Exact code and raw requests/responses are committed. Recompute and validate all counts with `PYTHONDONTWRITEBYTECODE=1 python3 poc/company-knowledge/finalize_evaluation.py`.

Verification passed: all52 IDs/prompts, every merged-file hash, response/body/request hashes, six cached judge batches and decisions, independently recomputed counts, original hidden/addendum/training hashes, Python syntax and scoped diff checks. No repository-wide CI was run; no base CI failure assessment was made.

Final evidence commit: `d9ae15ee2a4c19bc4bee3d78fb2c7751cbfd8baf`. Earlier sections below are historical checkpoints; this final result supersedes their pending status.


## Status
Preliminary base/retrieval results only. Training data is ready; LoRA has not run. The learning question and phase 1 recommendation remain undecided.

## Frozen evaluation — 2026-10-17T04:14:06Z
Hidden set written before any training examples. SHA-256: `aceed4dbde268e7f1a22cd6fcf99772a2e8b229e2dbe16645f97ba2a78ebb8ee`. Pack SHA-256: `b4d7aef08e0dbb39c3007c317648e964ff5ff8f388a44c7e87a71755589c4320`.

Files: `poc/company-knowledge/pack.json`, `sealed/hidden.jsonl`, `sealed/freeze.json` (paths relative to that folder). Ten invented facts across ten subjects, three environmental-check-before-replacement procedures. Hidden set: 20 unseen fact wordings, 5 two-fact questions, 1 unseen procedure with its full rule supplied, 10 untold questions, 10 unrelated prompts. The generator will read only the pack; hidden data is for final evaluation and post-generation overlap auditing. Separate development questions must select any training settings.

## Resource ledger
POC 2 has created no AWS resources, endpoints or imports yet. Kimi/GLM generation, review and scoring, and Qwen baseline/retrieval inference have incurred usage. The working 32K base import and S3 mirror are owned by POC 1 and retained for the pending LoRA comparison; POC 2 does not delete or mutate them.

## Initial AWS preflight (historical; superseded below)
Profile `box-hackathon`, selected Region `us-east-2`, AWS CLI 2.38.1. Free Tier plan query returned FREE / ACTIVE ($100 credit balance). Claude catalog lists inference-profile-only models; inspected Haiku profiles include us-east-1 and us-west-2 destinations, which conflict with the no-cross-Region rule. The us-east-2 budget command returned no budget data; this does not prove absence. POC 1 reports that the global Budgets endpoint requires a billing-Region exception and an alert recipient before creation. No spending until budget notification verified.

## Preliminary baseline comparison — 2026-10-17T05:34Z
These are real Bedrock inference results for **Qwen3-4B-Instruct-2507**, capped context32768, ARN `arn:aws:bedrock:us-east-2:549803795565:imported-model/0inmdc8ttj1w`. GLM-5 judged saved responses; no judge fallback. This is not a final LoRA learning verdict.

| Hidden category | Base | Base + retrieval | LoRA |
|---|---:|---:|---|
| New fact wordings | 0/20 | 19/20 | Pending |
| Two-fact questions | 0/5 | 5/5 | Pending |
| Held-out procedure, rule supplied | 1/1 | 1/1 | Pending |
| Untold questions: correct abstention | 10/10 | 10/10 | Pending |
| Unrelated prompts | 10/10 | 9/10 | Pending |
| Total correct | 21/46 | 44/46 | Pending |

On the ten untold questions, GLM marked zero invented answers in either mode. All92 responses stopped normally (no length truncation). The base already passes the single supplied-rule procedure test, so this baseline supplies no evidence that training is needed for that item.

Retrieval misses: H11 returned procedures P01/P02/P03 rather than the Kestrel owner fact; the lexical top3 control is imperfect. H39 (capital of Japan) retrieved irrelevant company documents and induced an abstention, while base answered correctly. Do not tune the retrieval control or hidden set against these outcomes in this experiment.

Training data ready:386 Kimi-only examples, GLM-reviewed, strict dedupe/overlap audit passed. Training SHA256 `92edb882d2233b7604b2072abe98c46d81dced97b0a54356788f160dddac1a72`; final manifest SHA256 `e2f7acfa96c583af99fb4fae7a045b626cabbf9ee380cedfdfe81da4278ec806`. Hidden hash remains the pre-generation value above. Haiku and partial DeepSeek outputs are labelled unused. Kimi US profile and routes were explicitly approved; GLM runs directly in us-east-2. Budget alert prerequisite waived by coordinator pending email; stop above$10/action.

Evidence: `poc/company-knowledge/evaluation/base-32k/summary.json`, SHA256 `b1a50b1596e015b34d39057e371ad49b7c13d8fc8e7c63a23705d5d6c039ce58`, plus verification.json, ten judge batches and92 request/body envelopes. Counts independently recomputed from cached GLM decisions and frozen IDs; all envelope/body/request hashes match. Source-template Jinja rendering matched all92 evaluation prompts. Score evidence commit `fa9e7587fce9d4f54546681c7461353cb0a457f2`.

Next: coordinator approved on-demand g6.2xlarge (g5 reserved for POC1), ≤3600seconds and<$10/action. POC2 waits for POC1's end-to-end train/merge/import proof, then uses its validated code for the predeclared seed17 run. Check imported-model occupancy before using slot3. Phase1 go/adjust/no-go recommendation remains pending actual LoRA results; no new Support cases or quota requests.

## Current combined v2 baseline — 2026-10-17T05:42Z
Tyson requested six additional procedure cases before POC2 training. The original46questions and training386rows remain unchanged. New cases cover both branches of each actual pack rule (E42 inlet pressure, R17 supply voltage, T09 ambient temperature), with new product settings, measurements, expected answers and rubrics. These are seen rules in new situations, not unseen procedure families. Rules are not supplied in these six prompts.

| Category | Base | Base + retrieval | LoRA |
|---|---:|---:|---|
| New fact wordings | 0/20 | 19/20 | Pending |
| Two-fact questions | 0/5 | 5/5 | Pending |
| Procedures, combined | 2/7 | 6/7 | Pending |
| Untold questions: correct abstention | 10/10 | 10/10 | Pending |
| Unrelated prompts | 10/10 | 9/10 | Pending |
| **Total correct** | **22/52** | **49/52** | **Pending** |

Procedure breakdown: original supplied-rule item1/1 both; six new seen-rule scenarios1/6 base vs5/6 retrieval. GLM marks four invented procedural claims in base's six new answers, none in retrieval; untold-question invented counts remain0/10 both. Two retrieval answers reached the fixed256-token limit. A02 chose the wrong repair despite having the correct rule; A03 was graded correct despite truncation and an early bullet contradicting its later correct conclusion. Retain GLM's raw49/52 score, with this manual caveat that A03 may be over-credited; no post-hoc rescore or token-limit rerun.

Seal manifest `poc/company-knowledge/sealed/addendum-v2-manifest.json` records both hashes: original `aceed4dbde268e7f1a22cd6fcf99772a2e8b229e2dbe16645f97ba2a78ebb8ee`, addendum `f8765dbf47a1cc5c12a93fa6be81e1e6ec737206cfb6fc6bf46d5ace37ad4457`. Same strict0.78 similarity audit against all386trainingrows passed; maximum nearest similarities0.295652–0.371278. No question revisions or training edits were needed. Training hash stays `92edb882d2233b7604b2072abe98c46d81dced97b0a54356788f160dddac1a72`. Addendum was explicitly commissioned after data generation and sealed before any POC2LoRA training.

All104responses/decisions validated across both modes; original46scorefile hash preserved. Combined result `poc/company-knowledge/evaluation/combined-v2.json`, SHA256 `52297c855cab3c4494806451ca98c7ee3bbb22bd3be022d2eed644bb5e0c1ec7`. V2questions/audit/scores committed as `a300cd5f6a8e821ad3c571f03bec92089b74c67c`. LoRA remains unrun; pre-training addendum gate is now committed, but POC1 train/merge/import proof is still required before g6 launch.

## POC2 training complete; candidate importing — 2026-10-17T06:15Z
Task7bfab9e1-f569-49a2-aee3-c6dfd15ae8c9; PRnone; base95fbdf43244f5af012beb05c761d6d3127e11dbf,head95fe01a094b37f6947f45776cccd3a1adfe63a46. Actual trainingreport:386examples,seed17,configured3epochs,LR0.0002,len512,accum4;288optimizersteps,Traineractualepoch2.974093 (record actual rather than claiming exactly3fullpasses). Guard:386scanned,max184tokens,zeroover512,zerotruncated; no lengthincrease/no rowsdropped byguard. Train333.992s,merge24.140s,hash/upload35.609s,peakCUDA8.823GB. SageMaker completed,590billableseconds,estimatedcompute590/3600*$1.222=$0.2002722 (not bill;excludesstorage/logs/importinference). Filteredguardlogquery returned noevents; ownS3trainingreport carriesguardcounts, do not claim logproof.

Live importcensus onlybase0inmdc8ttj1w,so no unexpectedoccupancy. Created tagged ownrole arn:aws:iam::549803795565:role/box-hackathon-poc2-s17-import-20261017, inlineReadOwnedMerged onlyown training/seed17/merged/*+prefixlist; trust Bedrock SourceAccount+regionaljobARN. Submitted tagged job arn:aws:bedrock:us-east-2:549803795565:model-import-job/fno0dcvahiag with candidate namebox-hackathon-poc2-s17-20261017; InProgress. Importusesavailableposition2afterPOC1smokedeletion, withinapproved3modelceiling. ImporthelperassertsQwen3/32768; metadataSHA matchtrainerreport,template64f85b198065d0fba2a81f37e10ed68161ce2c19a754c7100e67e0ca2ee9c326unchanged. Noendpoints. Ownbucket/roles/job/loggroupledger in evidence files.

Files import_role.py and8evidencefileslistedbycommit. Gates: actualSageMakercompletion/reportPASS; mergedmetadataSHA/architecture/context/templatePASS; importsubmissionPASS; roleAST/diffPASS. NoCIrun/baseCIfailureassessment. Import/inferencestillpending: hook9d8b6927-f508-4b1e-a64d-6420139a241e eachminute,30minTTL. Oncompletion boundedcoldcheck,thenfull52LoRAevalsamebaselineprompts/temperature0/max256/GLM5. No finallearningverdict untilscores; nohidden/trainingchanges,newquotaorSupportcalls.

## Coordinator retention decision — 2026-10-17T06:25:30Z
KEEP trained import arn:aws:bedrock:us-east-2:549803795565:imported-model/x2feesmws1lw after evaluation as potential pre-trained demo fallback. This explicit coordinator decision supersedes default deletion; coordinator will decide after verdict. Do not delete it. Cleanup only POC2-owned temporary roles/files/logs, preserving artifacts needed for retained fallback until coordinator decision. Coldstartwatch remains active; evaluation/verdict pending.

## POC2 Bedrock runtime blocker — 2026-10-17T06:35Z
Task7bfab9e1-f569-49a2-aee3-c6dfd15ae8c9,PRnone;base0468f131b249e1e52e5fdb760843e47655f7efa8,headdc70b0ad840322eb6e5cbbb79c9cda4d9a6aa215. Files evidence/seed17-cold-runtime.json andseed17-import-runtime-metadata.json. Candidatex2feesmws1lw completedimport but11completionreadinesscalls06:24:47.975–06:34:43.978UTC allModelNotReadyException,zeromodelresponses;10minboundedwatcherretired. Siblinganswer-libraryagent independentlyreportsfour-minuteretryfailure06:30:47–06:34:48; askeditstopduplicatecandidateretries. FreshGetImportedModel confirmsQwen3,1CMUv1.0; doesNOTproveruntimehealth. NoLoRAhiddenanswerorscoreexists; do NOT inferlearningfailureorsuccessfromservingfailure. Base/search52countsremain22/52vs49/52. Trainingguard/config/template/reportpreviouslyPASS,originalhiddenandv2/traininghashesunchanged.

Retaincandidatepercoordinator06:25decision,preserveownedS3mergedweights. Noquota/Supportrequest,newtraining,orchangedmodel/settings. DiffcheckPASS;noCIrun/baseCIfailureassessment. Infrastructureblockerrequirescoordinatorfallbackdecision: recommend singleboundedg6 evaluation-only job loadingexactmergedweights andrunning52sealedpromptstemp0/cap256,thenGLM5samejudge; clearlylabelSageMakerruntime andcomparabilitylimitationvsBedrockbaselines. ThiswouldseparateLoRAqualityfromBedrockservingfailure; notlaunchedwithoutcoordinatorrelease. PotentialnextalternativeAWSdiagnosticrequirescoordinatordecision. NoactivePOC2hooknow.

## Approved evaluation-only fallback launched — 2026-10-17T06:47Z
Tyson/coordinatorapprovedONEboundedon-demandg6evaluation-onlyjob,max3600s,$10cap,exactmergedweights,no training. Task7bfab9e1-f569-49a2-aee3-c6dfd15ae8c9,PRnone;prepcommitc647622cb70c40b7b6ce6888b76b9a79613c60ef,head0a682eae88b26f3820d4d70f21004142edff6576. Ownjob arn:aws:sagemaker:us-east-2:549803795565:training-job/box-hackathon-poc2-eval17-20261017,submitted06:47:20.513Z;ownscopedrole arn:aws:iam::549803795565:role/box-hackathon-poc2-eval17-20261017. Tagsproject=box-hackathon,poc=company-knowledge. FirstCreateTrainingJobrole-assumptionvalidationfailedbeforejobcreation;samename retryafterroleinspection succeeded. Exactrequest/errorretained. Ownbucketcontrol/evaluation/eval_runtime.py+prompts.json,outputevaluation/seed17/responses.json andevaluation/artifacts/;job-onlylogstreamprefix. Ledgerinseed17-evaluation-submission.json.

RuntimecodehasNOTrainer/optimizer;hashchecksEVERYmergedfileagainsttrainingreportbeforeload, usesexactcachedbaseline52prompts,greedydo_sampleFalse(max256newtokens,temp0equivalent),sameQwentemplate,outputsperanswerlabel **served via SageMaker/transformers, not Bedrock**. Scorer--sagemaker-responsesvalidateshiddenhashes/52IDs/exactprompts,runsidenticalGLM5rubric/batching,labelsresults;Bedrockcandidateisnotinvoked. Runtimechangeisconfound:do notattributegainsolelytoLoRA. CodeAST/diffPASS;IAMAutopilotoutputreviewedandscopedtoownprefixes,notdeployedwildcard;cachecleaned. NoCIrun/baseCIfailureassessment. Hookf8edc9ec-98fc-46f0-83d7-9406dd8a2500 minutechecks/75minTTL;initialPending.

Read-onlytokenizerdiagnosis: capturedsourceinventories+smallmetadataforbase,tiny-served,Poc2unreadyin evidence/tokenizer-comparison.json. Tiny-served andPoc2haveidenticalSHAfor config,generation_config,tokenizer_config,added_tokens,special_tokens_map;publishedtrainingreporthashesalsoagreefor tokenizer.json,merges.txt,vocab.json. BothtinyandPoc2haveextraadded/specialfiles,absenceof.gitattributes/version,samemergeslengthchange. ChattemplatePRESENTandunchangedSHA64f85b... frombase. Thuscopyingbasetokenizer/generationisNOTlikelyfixsupportedbythesedifferences;doesnotproveunderlyingBedrockfailurecause. Noartifactmodified,noreimport,newquota,Supportrequest. KEEPcandidatex2feesmws1lwpercoordinator. Finalcounts/verdictpendingfallback.
