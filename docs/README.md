# Company-knowledge learning demo

Planning documents and progress exported from the workspace at **2026-10-17 07:45 UTC**. Implementation is underway on `withered-cobra`; this `ideas` branch contains documentation only. The source notes include dated progress entries, so earlier open questions may be resolved in later entries.

## Plan and research

- [Demo specification](spec.md) — Box + AWS architecture, decisions, acceptance criteria and verification plan.
- [Training methods compared](research/training-methods-compared.md) — Comparison of learning approaches for company knowledge.
- [Demo scenarios](scenarios.md) — Demonstrations and hidden-test examples.

## Results and current work

- [POC 1 runbook and results](pocs/poc-1-runbook.md): AWS training/import/invocation mechanics passed; the tiny training run overfit.
- [POC 2 learning results](pocs/poc-2-results.md): **ADJUST**, with trained 39/52, base 22/52, search 49/52. Facts improved; abstention regressed. The original scores used SageMaker/transformers serving, not the initially unresponsive Bedrock import.
- [POC 3 runbook and results](pocs/poc-3-runbook.md): extraction and developer-token webhook delivery passed; later CCG authorization and signing-key setup are recorded. Live signed delivery remains a deployment check.
- [4B versus 8B experiment](experiments/model-comparison.md): both training jobs completed; evaluation scores and the model decision are **pending**. The exact-weight Bedrock re-import served, resolving the earlier readiness failure for that retry.
- [Phase 1 plan review](reviews/phase-1-plan-review.md): amendments reflected in current task notes.
- [Browser demo test](tasks/18-demo-browser-test.md): planned live proof after deployment.

## Phase 1b: medical corpus — in progress

The company-specific medical corpus replaces the Halvard pack for the next pipeline run; `public/` is excluded. At this snapshot, corpus access/inventory and a temporary webhook create/delete probe are recorded, while native extraction is underway. There is **no final approved medical snapshot, medical evaluation result, or promoted medical model yet**. Existing Halvard scores above are separate evidence.

- [Medical corpus snapshot task and probe progress](phase-1b/01-medical-corpus.md) — in progress.
- [Medical dev and sealed hidden sets](phase-1b/02-dev-and-hidden-sets.md) — not started.
- [Medical training and evaluation](phase-1b/03-training-and-evaluation.md) — not started.
- [OpenUI Ask interface](phase-1b/04-openui-chat.md) — in progress.

## Architecture reviews

- [Claude architecture review](reviews/architecture-review-claude.md)
- [Codex architecture review](reviews/architecture-review-codex.md)

## Tasks

### Phase 0: POCs

- [POC 1 — AWS learning path: SageMaker LoRA to Bedrock import](tasks/01-poc-1-aws-learning-path-sagemaker-lora-to-bedrock-import.md)
- [POC 2 — Does a small LoRA actually learn company knowledge?](tasks/02-poc-2-does-a-small-lora-actually-learn-company-knowledge.md)
- [POC 3 — Box CCG app, Box AI extraction and webhook delivery](tasks/03-poc-3-box-ccg-app-box-ai-extraction-and-webhook-delivery.md)

### Phase 1: Box + AWS managed LoRA

- [Scaffold repo layout and shared schemas](tasks/04-scaffold-repo-layout-and-shared-schemas.md)
- [Terraform foundation and deploy commands](tasks/05-terraform-foundation-and-deploy-commands.md)
- [Box client: CCG auth, files, versions, seeding](tasks/06-box-client-ccg-auth-files-versions-seeding.md)
- [Fictional company knowledge pack](tasks/07-fictional-company-knowledge-pack.md)
- [Box AI extraction, automatic checks and review](tasks/08-box-ai-extraction-automatic-checks-and-review.md)
- [Box sync service: webhook, schedule and Sync now](tasks/09-box-sync-service-webhook-schedule-and-sync-now.md)
- [Answering library: without, with, and search](tasks/10-answering-library-without-with-and-search.md)
- [Training pipeline: Step Functions, SageMaker LoRA, Bedrock import](tasks/11-training-pipeline-step-functions-sagemaker-lora-bedrock-import.md)
- [Evaluation with Bedrock judge, Evaluations jobs and promotion gate](tasks/12-evaluation-with-bedrock-judge-evaluations-jobs-and-promotion-gate.md)
- [Web app on AWS: API, shared-password login and screens](tasks/13-web-app-on-aws-api-shared-password-login-and-screens.md)
- [Deploy, seed and demo runbook](tasks/14-deploy-seed-and-demo-runbook.md)

### Phase 2: TensorFold facts (deferred beyond the hackathon)

- [Phase 2: TensorFold feasibility on EC2 Mac](tasks/15-phase-2-tensorfold-feasibility-on-ec2-mac.md)
- [TensorFold fact teaching and Box sync](tasks/16-tensorfold-fact-teaching-and-box-sync.md)
- [Phase 2: add the TensorFold track to inference, evaluation, UI and demo](tasks/17-phase-2-add-the-tensorfold-track-to-inference-evaluation-ui-and-demo.md)
## References

- [Enterprise business value: Box workflows that learn from expert corrections](references/box-learning-enterprise-business-value-2026-10-16.md) — Research reference: box learning enterprise business value 2026 10 16.
- [Box skills + weight learning: independent hackathon ideation](references/box-weight-learning-hackathon-ideas-2026-10-16.md) — Research reference: box weight learning hackathon ideas 2026 10 16.
- [Box Agent Skills × real weight learning — ideation & vetting (Opus 5.5, tool-assisted)](references/box-weight-learning-opus55-research-2026-10-16.md) — Research reference: box weight learning opus55 research 2026 10 16.
- [Enterprise learning opportunities: business value, training evidence and recent funding](references/enterprise-learning-ranking-and-funding-2026-10-16.md) — Research reference: enterprise learning ranking and funding 2026 10 16.
- [Recent funding in enterprise AI workflows, and what it establishes about learning](references/enterprise-startup-funding-jul16-oct16-2026.md) — Research reference: enterprise startup funding jul16 oct16 2026.
- [Enterprise use cases for a Box-skills + persistent-weight-learning POC: business value vs. learning value](references/enterprise-use-case-ranking-opus55-2026-10-16.md) — Research reference: enterprise use case ranking opus55 2026 10 16.
- [TensorFold, LoRA and the October 2026 Nemotron launch](references/nemotron-learning-launch-2026-10-16.md) — Research reference: nemotron learning launch 2026 10 16.

The reference reports are copied unchanged. Their links to `enterprise-opus55-ranking-evidence-2026-10-16/run-metadata.json` refer to evidence files intentionally excluded from this export.
