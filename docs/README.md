# Company-knowledge learning demo

Planning documents exported from the workspace; implementation has not started.

## Plan and research

- [Demo specification](spec.md) — Box + AWS architecture, decisions, acceptance criteria and verification plan.
- [Training methods compared](research/training-methods-compared.md) — Comparison of learning approaches for company knowledge.
- [Demo scenarios](scenarios.md) — Demonstrations and hidden-test examples.

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

### Phase 2: TensorFold facts

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
