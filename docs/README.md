# Company-knowledge learning demo

Planning documents exported from the workspace; implementation has not started.

## Plan and research

- [Demo specification](spec.md) — Goals, decisions, acceptance criteria, and verification plan.
- [Training methods compared](research/training-methods-compared.md) — Comparison of learning approaches for company knowledge.

## Tasks

- [Cloud machine feasibility check for TensorFold and LoRA](tasks/01-cloud-machine-feasibility-check-for-tensorfold-and-lora.md) — Prove, in about an hour, that the chosen cloud machine can teach TensorFold one fact and run a LoRA training step. Everything else depends on this.
- [Scaffold project and knowledge-pack schema](tasks/02-scaffold-project-and-knowledge-pack-schema.md) — Set up the Python project and the shared data formats every other task uses.
- [Document source adapter for Box with local-folder fallback](tasks/03-document-source-adapter-for-box-with-local-folder-fallback.md) — One interface for listing, reading and writing documents, backed by Box or by a local folder, and able to tell which files changed since the last run (needed for the Box-sync demo).
- [Fictional company knowledge pack](tasks/04-fictional-company-knowledge-pack.md) — Invent a small fictional company whose facts and procedures the base model cannot already know, with test questions for every demo story.
- [Retrieval and inference pipeline with baseline modes](tasks/05-retrieval-and-inference-pipeline-with-baseline-modes.md) — One way to ask any model a question so all approaches are compared on identical inputs.
- [Review queue for extracted facts and procedures](tasks/06-review-queue-for-extracted-facts-and-procedures.md) — A person (or a simulated reviewer) approves what gets taught, so nothing enters the model's weights without sign-off.
- [TensorFold fact teaching and Box sync](tasks/07-tensorfold-fact-teaching-and-box-sync.md) — Teach approved facts one at a time through TensorFold, record what stuck, and keep the model in step with Box edits.
- [LoRA procedure training and adapter registry](tasks/08-lora-procedure-training-and-adapter-registry.md) — Teach procedures (conditional, multi-step behavior) with LoRA, the part TensorFold cannot learn, and keep every adapter as a numbered version.
- [Evaluation harness and promotion gate](tasks/09-evaluation-harness-and-promotion-gate.md) — Score every approach on the same held-out questions and decide what gets kept.
- [End-to-end loop runner and demo script](tasks/10-end-to-end-loop-runner-and-demo-script.md) — One command runs the whole loop and a script walks through the three demo stories and the Box-sync finale.

## References

- [Enterprise business value: Box workflows that learn from expert corrections](references/box-learning-enterprise-business-value-2026-10-16.md) — Research reference: box learning enterprise business value 2026 10 16.
- [Box skills + weight learning: independent hackathon ideation](references/box-weight-learning-hackathon-ideas-2026-10-16.md) — Research reference: box weight learning hackathon ideas 2026 10 16.
- [Box Agent Skills × real weight learning — ideation & vetting (Opus 5.5, tool-assisted)](references/box-weight-learning-opus55-research-2026-10-16.md) — Research reference: box weight learning opus55 research 2026 10 16.
- [Enterprise learning opportunities: business value, training evidence and recent funding](references/enterprise-learning-ranking-and-funding-2026-10-16.md) — Research reference: enterprise learning ranking and funding 2026 10 16.
- [Recent funding in enterprise AI workflows, and what it establishes about learning](references/enterprise-startup-funding-jul16-oct16-2026.md) — Research reference: enterprise startup funding jul16 oct16 2026.
- [Enterprise use cases for a Box-skills + persistent-weight-learning POC: business value vs. learning value](references/enterprise-use-case-ranking-opus55-2026-10-16.md) — Research reference: enterprise use case ranking opus55 2026 10 16.
- [TensorFold, LoRA and the October 2026 Nemotron launch](references/nemotron-learning-launch-2026-10-16.md) — Research reference: nemotron learning launch 2026 10 16.

The reference reports are copied unchanged. Their links to `enterprise-opus55-ranking-evidence-2026-10-16/run-metadata.json` refer to evidence files intentionally excluded from this export.
