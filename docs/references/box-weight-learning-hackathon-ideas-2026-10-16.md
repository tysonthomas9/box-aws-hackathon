# Box skills + weight learning: independent hackathon ideation

Date: October 16, 2026. Scope: proposals and critical review, not implementation or measured model performance. The user requested independent ideas from Astra and Claude. No authenticated Box connection or training runtime has been verified.

## Astra's independent review

Model: `gpt-6-astra`. Verdict: **Second Draft** is the strongest learning demo if approved revision pairs are available; **Field Translator** is the safer Box-centered product demo.

| Rank | Idea | What the model learns | Main objection |
| --- | --- | --- | --- |
| 1 | Second Draft | Recurring transformations in accepted edits: concision, tone, structure and terminology | A style guide plus retrieved examples may match it; Box is a useful document lifecycle, but not unique |
| 2 | Field Translator | Semantic mappings from varied document wording to the organization's schema | Box extraction with good field definitions is a strong baseline |
| 3 | Evidence Apprentice | Whether a passage satisfies a requirement, including near misses and abstention | Reliable sufficiency labels are difficult to obtain |
| 4 | Box Apprentice | Content-based routing into stable logical destinations | Rules or a conventional classifier may suffice |
| 5 | Review Radar | Which passages a reviewer is likely to comment on, and why | Preferences may be inconsistent; avoid presenting attention as authoritative risk judgment |
| 6 | Visual Form Apprentice | Layout/image-to-field mappings for unfamiliar forms | Requires a separately verified multimodal training stack and representative images |
| 7 | Workflow Apprentice | Structured action plans from approved demonstrations | Templates can beat training for fixed workflows |
| 8 | Living Glossary | A few stable factual associations in TensorFold's added neurons | Retrieval is usually more practical for mutable, cited, permission-scoped knowledge |

### Second Draft

Demo an unseen customer update with entirely new facts. Compare the base model's revision against its revision with the trained adapter enabled. The target is an editor's recurring transformations, not memorization of names, numbers, facts or changing policies.

Use explicitly approved draft/revision pairs. Hold out whole source documents and topics, grouping all versions together. Compare against the same model with an explicit style guide and relevant examples. Measure blinded preference, remaining editing effort and factual preservation. Include already-good passages to penalize unnecessary rewriting. Limit the first POC to one editor, one document type and paragraph-level text suggestions; defer DOCX layout and tracked-change fidelity.

Box supplies drafts, approved counterparts, review comments and output destinations. The skills guide those operations. This is meaningful integration, but the learner could work with another document store.

### Field Translator

Demo a narrow document class, such as vendor statements of work, and roughly five fields. Distinguish committed deliverables from optional services and map varied wording into canonical categories. Train on reviewer-confirmed field values with supporting source spans, then test a held-out vendor's wording.

Keep arithmetic, date parsing, IDs and output validation deterministic. Compare against Box extraction with clear field definitions and a few-shot local-model baseline using the same source information. Split by vendor/template family. Measure field correctness, unsupported values and appropriate abstentions. Start with proposed metadata; actual metadata writes are optional and depend on configured tools.

### Evidence Apprentice

Demo a project intake checklist where a convincingly titled document is insufficient, while an unexpectedly titled document contains the necessary evidence. Labels are requirement/passage pairs marked supported, insufficient or needs review, with supporting spans.

Hold out complete projects and requirement-paraphrase families. Include contradictions and persuasive near misses. Report false-complete decisions separately. Compare against retrieval plus a prompted model with the explicit checklist. Limit the POC to one ordinary operational checklist and short cited passages; avoid autonomous approval or broad compliance claims.

## Shared proof requirements

- Freeze the evaluation documents before training and group related document versions/templates to prevent leakage.
- Keep evaluation prompts and source information fixed between adapter-off and adapter-on runs.
- Save an identifiable weight artifact and show successful reload after restarting inference.
- Report failures and retained behavior as well as improvements; a single correction does not establish generalization.
- Distinguish LoRA behavior learning from TensorFold factual insertion and from prompt/rule/retrieval updates.
- Choose the model and training configuration after checking actual hardware, available labels and the hackathon duration.

## Capability sources checked by the supervising agent

- [Box skills repository](https://github.com/box/skills): runtime instructions; separate Box authorization is needed.
- [Box MCP tool catalog](https://docs.box.com/en/box-mcp/tools): search, content, extraction and workflow capabilities; some writes are off by default.
- [MLX-LM training guide](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md): LoRA/quantized-base training, saved adapters and generation with adapters for supported architectures.
- [Pinned TensorFold Living Weights documentation](https://github.com/ashhart/TensorFold/blob/b090e3b19014bfa1eb2b7f38ea3cc4d39abec9be/docs/living-weights.md): narrow Nemotron Lightning factual-memory implementation and reported limitations.


## Claude's independent review

Claude was given the capability summary and starting document-routing candidate, without Astra's recommendations. Execution used the Claude task-driver skill, a private disposable working directory, safe mode, no available tools, no MCP servers and no slash commands. The actual model reported by the CLI was `claude-sonnet-5`.

- Session: `6ec44f08-c342-4193-8f32-993a2b99937c`.
- Mode: one-shot print mode, JSON result; one turn; 196.817 seconds reported duration.
- CLI list-price usage estimate: $0.1820722. Authentication used the Claude.ai Max subscription; this estimate is not an asserted additional invoice charge.
- Web searches: 0. Permission denials: none. No task tools, source edits, Box operations or training runs.

### Supervising-agent review of the response

Claude independently chose **field disambiguation** as the winner. Astra independently ranked the closely related **Field Translator** second, behind **Second Draft**. This agreement supports prioritizing a small extraction experiment, but is not evidence that fine-tuning will outperform a strong prompt.

Corrections and qualifications to Claude's response below:

1. **Collecting correction labels does not require Box metadata writes.** A reviewer UI can store approved labels locally. Metadata-write enablement matters only if that specific Box persistence integration is chosen. Read-only extraction plus local labels is a valid first POC.
2. **Small evaluation sets can have measured accuracy.** Report counts and denominator, uncertainty, unsupported-value errors and failure examples; avoid claiming broad statistical generalization from a tiny sample.
3. **Routing data should group related documents and templates.** A plain random document split may leak near-duplicates or repeated templates. The stricter grouping in Astra's/shared evaluation guidance is preferable.
4. **Check persistence directly.** Verify saved/reloaded tensor identity and evaluate under fixed inference settings. Repeated sampled outputs need not be identical merely because weights were reloaded correctly.
5. **Contract risk and permission auto-approval are not recommended first demos.** They introduce consequences, labeling difficulties and stronger deterministic/rule-based alternatives. Claude's legal idea remains a proposal, not verified legal capability or advice.
6. **LoRA normally updates the configured adapter matrices.** Claude's phrase 'classification-style output head/behavior' is not proof that a separate output head would be trained; exact trainable targets need implementation-time verification.

### Claude's returned text

Independent ideation only — I did not look for or assume another model's output. Nothing below reflects any tool use, file access, or training; it's reasoning against the verified-context summary provided.

## 1. Eight ideas, ranked by defensibility of needing *weight* changes

| # | Idea (tech) | What the weights would learn | One-line value |
|---|---|---|---|
| 1 | Invoice/field disambiguation adapter (LoRA/QLoRA) | A context-dependent rule for which extracted candidate value is "canonical" for an ambiguous field, generalized across vendor layouts | Finance stops manually re-resolving the same ambiguous field on every invoice |
| 2 | Document intake & routing — the given baseline (LoRA/QLoRA) | Document text → destination-label mapping, from reviewer corrections | New Box uploads land in the right folder without a human triage pass |
| 3 | Clause-deviation / redline risk flagging (LoRA/QLoRA) | What counts as a deviation from the org's standard contract terms, from prior accepted/rejected redlines | Legal gets an early flag when a new contract draft departs from house terms |
| 4 | Org glossary fact-injection from a handbook (TensorFold) | A handful of discrete facts grown into dedicated neurons | Instant correct jargon recall without a retrieval hop (explicitly fragile at scale, per the published 6/16 result) |
| 5 | Reviewer redaction/style adapter (LoRA/QLoRA) | A per-reviewer stylistic transform on extracted text | Summaries/redactions match one reviewer's house style automatically |
| 6 | Low-stakes share/permission auto-approval (LoRA/QLoRA) | An approve/deny boundary from historical admin decisions | Routine Box sharing requests get decided like the admin would — **likely doesn't need an LLM at all** |
| 7 | Personalized query→destination resolution ("pull up Q3 numbers") (LoRA/QLoRA) | User-specific referent resolution | Ambiguous queries resolve to the right file for *this* user — **likely beaten by retrieval over interaction history** |
| 8 | Team-voice comment drafting (LoRA/QLoRA) | Tone/phrasing transfer | Drafted comments sound like the team wrote them — classic few-shot territory, weak differentiation |

Items 6–8 are included deliberately as the "this probably doesn't earn weight training" control group the brief asked for.

## 2. Top three, expanded

**#1 Invoice/field disambiguation adapter**
- *Demo:* Feed unseen invoices from vendors not in training; show the adapter picks the field the finance team would, base model doesn't.
- *Data/labels:* Box-extracted invoice text + the corrected canonical value, from the organization's existing review/correction history (not synthetic).
- *Exact change:* LoRA weights on a small base model shift output logits toward the org's resolution rule for 2–3 ambiguous field types; behavior change is "pick field X" not "recite fact."
- *Why training > rules/few-shot:* The resolution rule is implicit and vendor-layout-dependent; a prompt would have to enumerate dozens of heuristics (effectively re-encoding the training set as text), and this should be treated as a hypothesis to test, not assumed true.
- *Leakage-free test:* Vendor-level split (not document-level) so no vendor's layout appears in both train and held-out — otherwise the model could pattern-match layout rather than learn the rule.
- *Box role:* Extraction only (read-only, verified capability); correction labels come from existing reviewer workflow.
- *Dependencies/failure mode:* Needs Box metadata write/correction history actually populated and enough distinct vendors — unverified for any given account; most likely failure is that 10 examples reveal a simple deterministic rule, collapsing the need for training entirely.

**#2 Document intake & routing (pragmatic fallback, the given starting idea)**
- *Demo:* New, never-seen document dropped in; adapter emits a destination label the base model gets wrong.
- *Data/labels:* Document text/summary → reviewer-approved destination label.
- *Exact change:* LoRA weights shift a classification-style output head/behavior toward the org's folder taxonomy.
- *Why training > rules/few-shot:* Weakest justification of the three — whole-document classification is a textbook case where a lightweight embedding or classical classifier plausibly matches an LLM adapter at a fraction of the cost; this should be explicitly tested, not assumed.
- *Leakage-free test:* Document-level held-out split, frozen prompt, base-vs-adapter comparison on the same unseen set.
- *Box role:* Listing/content read + metadata for destination labels; actual folder moves need admin-enabled write tools (off by default per context) — the demo can emit a label without exercising the move itself.
- *Dependencies/failure mode:* Fast to build, lowest technical risk; most likely failure is "it works but a non-LLM baseline would have worked just as well," which is a legitimate hackathon finding, not a failure to report honestly.

**#3 Clause-deviation / redline risk flagging**
- *Demo:* New contract draft flagged against org-standard terms the adapter was never shown verbatim.
- *Data/labels:* Prior contract redlines with accept/reject outcomes, sourced via Box extraction.
- *Exact change:* LoRA weights encode a learned notion of "deviates from our norm" over clause text, distinct from simple keyword matching.
- *Why training > rules/few-shot:* Most substantive of the three — legal risk judgment is genuinely hard to hand-write as rules — but also highest data-scarcity risk.
- *Leakage-free test:* Split by contract/counterparty, not by clause, since similar clauses recur across a single counterparty's contracts.
- *Box role:* Extraction of clause text and historical redline/approval metadata.
- *Dependencies/failure mode:* Realistically needs more labeled redlines than a hackathon is likely to have; most likely failure is overfitting to a handful of counterparties and mistaking that for generalization.

## 3. Recommendation

I'd pick **#1, the invoice/field disambiguation adapter**, over the given baseline (#2). My reasoning: the brief's own skepticism cue — "classification may not need an LLM" — applies most sharply to #2's whole-document routing, which is a solved problem for classical/embedding methods; #1 instead requires reading surrounding context to resolve a within-document ambiguity, which is a more defensible prior for needing a language model's weights at all, let alone fine-tuned ones. #3 is the most substantive decision but the least likely to have enough labeled examples in a hackathon window to avoid pure memorization. None of these claims should be taken as proven — they're priors, and the honest hackathon output should include an ablation (adapter vs. strong few-shot prompt on the same held-out set) rather than asserting training won.

What would change the choice: if the Box account's correction/metadata-write loop turns out not to be enabled (write tools are admin-gated per context), none of these can source live labels and all would need a static exported correction set, which weakens the "Box skills in the loop" story equally. If a quick look at ~10 real examples shows the ambiguous-field resolution is actually a simple deterministic rule, #1 collapses and #2 becomes the safer choice purely on feasibility grounds. If hardware/time can't sustain even a small LoRA/QLoRA train+reload cycle (unverified for this session's environment), fall back to #2 for its smaller, more uniform input representation and likely faster convergence.

## 4. Minimal hackathon slice and proof of persisted learning

Minimal slice: one Box source of documents with a recurring, genuinely ambiguous extracted value; use Box skills/MCP purely for read-only extraction to produce (text, corrected-label) pairs; freeze one system prompt used identically in every run.

To demonstrate real, persisted weight learning rather than a prompting or caching artifact: split labeled examples into train/held-out *before* any model touches them, with no document (or, for #1, no vendor) crossing the split. Train a LoRA/QLoRA adapter on train only and save it to disk. Then, with the frozen prompt and the same unseen held-out documents: (a) run the base model alone, (b) run base+adapter in the same process, (c) fully exit the process, reload the base model and the saved adapter from disk with no retraining, and rerun the identical held-out documents — matching output between (b) and (c) is the evidence that the change lives in the saved weight file, not in session state. This demonstrates the mechanism worked; it does not establish an accuracy number, since a hackathon-sized held-out set is unlikely to be large enough to support one, and no claim about training completing within a given time budget is warranted without knowing the hardware. No files were changed and no commands were run in producing this analysis.

## Combined recommendation

Start with **Field Translator** if representative documents and corrected field labels exist. Select one ambiguous semantic field-selection problem and compare Box extraction with clear definitions, a few-shot local model, and the same local model with a trained adapter. Choose **Second Draft** instead if accepted draft/revision pairs are the strongest data asset. Keep **Evidence Apprentice** as the ambitious option and **Box Apprentice** routing as the practical fallback.

The next decision should be driven by available labeled examples, actual training hardware and hackathon duration. None of these ideation reviews measured training time, model fit, or an accuracy gain.


## Claude Opus 5.5: original brief, no tools

The user requested Opus 5.5 after the earlier Sonnet run. A fresh session received the exact original brief recovered from the prior session's first user message, without prior model responses. Official model identifier verified at https://platform.claude.com/docs/en/models/opus-5-5/overview .

- Actual CLI model: `claude-opus-5-5`.
- Session: `e1f3b14b-2ba7-43b2-9455-95afc4f08239`.
- Mode: one-shot print mode, safe mode, no tools/MCP/skills; one turn, 54.725 seconds.
- CLI list-price usage estimate: $0.120231, using Claude.ai Max authentication; not an asserted additional invoice charge.
- Web searches by Opus: 0. Permission denials: none. No model training or Box operations.

### Supervising review

Opus introduced **Compiled Skills**, which directly combines the Box skills curriculum with weight learning. Its proposed advantage over long prompts remains unmeasured. A schema-valid plan is not necessarily semantically correct or executable, and mock-tool performance is not proof of real Box integration.

Its top-ranked **Redline Apprentice** needs stronger labeling than simply treating every executed contract as the organization's preferred position: negotiated outcomes may reflect counterparty compromises. Legal judgments remain with qualified reviewers. Mutable policies, identities, permission checks and Box IDs should remain explicit at runtime rather than being enforced through learned weights.

The most useful next feasibility test for Compiled Skills is a four-way comparison: base/minimal instructions, base/full skills, adapter/minimal instructions and adapter/full skills, with the same live tool schemas and runtime safeguards in every arm. Hold out workflow compositions, not just wording variants. Version the skills and tool schemas used for training.

### Returned Opus text

# Box Skills + Weight Learning: Hackathon POC Ideation

**Scope:** This is reasoning only. I ran no commands, changed no files, used no tools, and accessed no Box account. I relied only on the verified context you gave me. New assumptions are marked **[unverified]**.

## 1. Ideas, ranked

| # | Idea | User value (one sentence) | What the weights learn |
|---|---|---|---|
| 1 | **Redline Apprentice** | First-pass contract redlines that already reflect the org's negotiating positions. | A clause-to-house-position *transformation*, learned from before/after document pairs. |
| 2 | **Compiled Skills (skill-to-weights distillation)** | A small local model plans Box workflows correctly without a long SKILL.md in context. | Procedural mapping from a request to a valid Box MCP tool-call plan, distilled from teacher traces. |
| 3 | **Extraction Normalizer + Doubt Flag** | Box AI extraction output becomes clean, org-canonical metadata, and suspect fields get flagged. | Mapping raw extracted fields to the org's canonical values, plus a learned "needs human review" signal. |
| 4 | **Reviewer-Voice Commenter** | Draft review comments in the style and policy of the org's senior reviewers. | Mapping from a document section to a comment, using historical Box comments. |
| 5 | **Box Apprentice intake (pragmatic fallback)** | New documents get routed to the right logical destination. | Document-to-label classification learned from approved corrections. |
| 6 | **Version-Diff "What Matters" Summarizer** | Change summaries that surface only the changes this org cares about. | Salience judgments over diffs, learned from what reviewers marked as material. |
| 7 | **TensorFold Living Policy Memory** | Stable org facts, such as approval thresholds, are recalled without retrieval. | Discrete facts written into added MoE neurons on Nemotron 3.5 Lightning only. |

**Why the order looks like this.** Ideas #1 and #2 involve recurring, substantive transformations or procedures. Prompts and retrieval tend to approximate these poorly at small model scale **[unverified]**.

The lower-ranked ideas each have a cheaper competitor:
- **#5** may not need an LLM. Logistic regression over embeddings is a mandatory baseline.
- **#7** competes poorly against retrieval. The published result was 6 of 16 correct with interference, and it supports only one model. It suits a research side-demo, not the main entry.

## 2. Top three, expanded

### #1 Redline Apprentice

**Live demo.** Pick an unseen vendor MSA from a Box folder. Run the same frozen prompt three ways:
- the base model,
- the base model with the playbook retrieved plus few-shot examples,
- the base model with the adapter.

The adapter version should rewrite the limitation-of-liability clause to the org's fallback position (e.g., cap tied to fees, with specific carve-outs) while preserving the counterparty's defined terms.

**Data and labels.** Use pairs of a counterparty draft and the final executed version of the same clause. Candidate sources are Box file versions or sibling "redlined" files. Whether usable pairs exist in sufficient number is **[unverified]** and is the central risk. Restrict scope to one or two clause families.

**What changes.** LoRA matrices on attention and/or MLP projections of a small MLX-supported instruct model. The model choice and size are **[unverified]**. The expected behavior change is that the model's default rewrite moves toward house positions without being told those positions in the prompt.

**Why train instead of using prompts or retrieval.**
- A playbook says *what* the position is.
- Pairs teach *how* to edit real text into that position: minimal edits, preserved defined terms, and the org's drafting idiom.
- Few-shot prompting is the baseline the adapter must beat. It may well win when there are few pairs.

**Leakage-free test.**
- Split by counterparty and template family, not by clause.
- Near-dedupe across the split.
- Score with a checklist of required positions (cap present, carve-outs present, no new obligations) plus a blind reviewer preference among the three variants.

**Box and skills role.** Skills guide discovery and content and version retrieval via MCP. Output goes back as a comment or a new uploaded file only if those tools are enabled. Otherwise it is displayed locally.

**Dependencies.** Real paired data, legal sensitivity clearance, and a model that fits the unknown hardware.

**Likely failure.** Too few pairs. The adapter then overfits phrasing, or few-shot ties it.

### #2 Compiled Skills

**Live demo.** A request like "find last quarter's signed SOWs for Acme and extract renewal dates" goes to:
- a small model with the full SKILL.md in context,
- the same small model with an adapter and a minimal prompt.

Compare plan validity, token count, and latency.

**Data and labels.** A strong teacher agent that follows the Box skills produces tool-call plans against the documented MCP tool schemas. Plans are validated by a schema checker and, optionally, by dry runs. The data volume is controllable.

**What changes.** LoRA weights on the student model. Procedural knowledge (auth steps, search before content, which tool does extraction) moves from context into weights.

**Why train instead of using prompts.** The skill text costs context and latency every call, and small models follow long instructions inconsistently **[unverified]**. This is the only idea where the "skills" themselves become the thing that is learned.

**Leakage-free test.** Held-out request *templates*, not just paraphrases. Include unseen tool combinations. Measure schema-valid plan rate and step-order correctness.

**Box and skills role.** Skills are the teacher curriculum. The MCP tool docs define the action space.

**Dependencies.** Real tool availability per account is **[unverified]**. The evaluation can run offline against mocked schemas.

**Likely failure.**
- The student memorizes plan templates and breaks on novel compositions.
- The teacher's errors get distilled into the student.
- It is less "org-specific" than judges may expect.

### #3 Extraction Normalizer + Doubt Flag

**Live demo.** Box AI extracts vendor, cost center, and term from invoices. The adapter outputs canonical values (e.g., "Acme Corp EMEA" mapped to vendor ID label V-0142) and flags low-confidence fields. A reviewer correction is fed back, a retrain runs, and the corrected pattern now holds on a fresh document.

**Data and labels.** Pairs of Box AI extraction output and reviewer-approved metadata values.

**What changes.** A LoRA on a small model that maps raw text plus the extraction to canonical JSON with a flag.

**Why train.** Most normalization is solvable with lookup tables and fuzzy matching. Training earns its keep only on contextual cases, such as cost center inferred from line items. A rules baseline is mandatory.

**Leakage-free test.** Held-out vendors and time-split documents. Measure field-level exact match and flag precision against the rules baseline.

**Box and skills role.** The Box-native extraction and metadata skills. Metadata writes are off by default and need admin configuration, so the demo should show proposed values.

**Likely failure.** Rules win, and the LLM adds latency without measurable gain.

## 3. Recommendation

**Primary: Redline Apprentice, if roughly a few hundred clause pairs from realistic contracts can be sourced or credibly constructed.** The adequate count is **[unverified]**. This idea:
- targets a recurring, high-value transformation,
- has a natural label source (versions and executed copies),
- gives judges a vivid side-by-side,
- forces a fair fight against few-shot prompting and retrieval.

**Candid caveat.** If the pairs are synthetic, the demo risks being "the model learned my generator." That is close to the artificial memorization you want to avoid.

**What would change the choice:**
- **No realistic paired data:** switch to **Compiled Skills**. It generates its own valid training data and has a measurable cost and latency payoff.
- **Weak hardware or a very short hackathon:** fall back to **Intake (#5)** or **#3**, presented honestly against an embedding classifier and a rules baseline.
- **Mandatory TensorFold use:** run #7 as a scoped side-experiment on Nemotron, framed explicitly as experimental factual memory with retrieval as the comparator.

## 4. Minimal hackathon slice and proof of persisted learning

**Slice.** One clause family, one small MLX-supported model **[unverified]**, read-only Box access via MCP for retrieval, and local display of output.

**Protocol to show that learning actually persisted:**
1. **Freeze the prompt.** Commit the exact prompt string and record its hash before training.
2. **Run the baseline.** Base model with the frozen prompt on a held-out set split by counterparty. Also record the few-shot and retrieval baselines.
3. **Train the LoRA.** Save the adapter and record its file hash and timestamp. Report the actual training time measured, not a promised one.
4. **Restart the process.** Load the base model plus the saved adapter from disk in a fresh process.
5. **Re-run the same held-out documents** with the identical prompt hash. Show:
   - the adapter hash differs from any prior adapter, or is newly present,
   - outputs differ from base,
   - checklist scores and blind preference, with n stated.
6. **Toggle the adapter off.** Behavior should revert, which shows the change lives in the weights.
7. **Optional: demonstrate incremental learning.** Feed in one reviewer correction, retrain to a new adapter version, reload, and test on a *different* unseen document with the same pattern.

**Claims discipline.** Report only the measured numbers with sample sizes. Say plainly when few-shot ties or beats the adapter. Make no claims about generalization beyond the clause family tested.


## Latest: Opus 5.5 rerun with all built-in tools

The user requested independent source research with full tool availability. Opus inspected three public repository snapshots and Box documentation, then ranked: (1) correction-trained router, (2) contract-variance disposition triage, (3) skill-procedure distillation, (4) extraction post-corrector, and (5) data-room request mapping. The ranking changed from its reasoning-only answer. These are judgment calls, not measured application results.

The [tool-assisted report](/Users/tyson/codebase/code-agents/sept/references/box-weight-learning-opus55-research-2026-10-16.md) contains source pins, technical qualifications and session metadata. It supersedes the earlier Opus feasibility judgments. The practical candidate is routing; the more distinctive Box-skills learning experiment is procedure distillation. Both still require real baselines and a training feasibility check. No Box account operations or training runs occurred.
