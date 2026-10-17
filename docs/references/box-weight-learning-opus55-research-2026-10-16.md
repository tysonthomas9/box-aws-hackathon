# Box Agent Skills × real weight learning — ideation & vetting (Opus 5.5, tool-assisted)


Research date: October 16, 2026. Requested model: **Claude Opus 5.5**, confirmed by CLI initialization and usage metadata. All built-in tools were available; automatic permission review was enabled. Project customizations and external MCP connections were disabled; no Box account connection was established.

This report preserves Opus's tool-assisted ranking, with supervising edits to qualify unmeasured claims. Codex independently checked repository cleanliness/revisions, MLX's frozen-base adapter setup, tool-schema dataset handling, backward/save paths and adapter reload validation, plus TensorFold's per-layer pocket allocation. No runtime learning or Box acceptance test was performed. The earlier reasoning-only recommendations remain historical comparisons, not the latest review.

- Session: `04d09fb8-380b-4348-957c-00255fede71e`.
- Execution: one-shot print mode with streaming JSON; 31 turns, 357.318 seconds reported duration.
- Main model: `claude-opus-5-5`. CLI usage metadata also reports `claude-haiku-5-5` for internal web/search processing; this did not replace the main ideation model.
- Reported list-price usage estimate: **$1.2755507** via Claude.ai Max authentication, not an asserted additional invoice charge.
- Observed tools: 23 Bash calls, 3 WebSearch calls, 2 WebFetch calls, 1 ToolSearch call and 1 Write call (the report). Permission denials: none.
- Worker-created public repo snapshots were clean and had no additional linked worktrees. Only the current task's temporary artifacts were created; canonical checkouts and Loom tickets were untouched.

Source pins independently checked:

- [Box skills 84320fd](https://github.com/box/skills/tree/84320fd8984b95cab430335cd341d8314c14bbcb)
- [MLX-LM 93e6d4a](https://github.com/ml-explore/mlx-lm/tree/93e6d4a6447b3080861985947f0820e76fcb957d)
- [TensorFold 6ee828c](https://github.com/ashhart/TensorFold/tree/6ee828c24bf802cdd73507d6fc60bb27a82c0d66)
- [MLX adapter load/validation](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/tuner/utils.py#L123), [training setup](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/lora.py#L225), [tool-schema data handling](https://github.com/ml-explore/mlx-lm/blob/93e6d4a6447b3080861985947f0820e76fcb957d/mlx_lm/tuner/datasets.py#L59)


Evidence tags: **[code]** read in cloned source · **[doc]** read in a fetched primary doc · **[inferred]** my reasoning · **[unknown]** not verified. Nothing was trained, installed, authenticated, or run against Box.

## 1. Ranked ideas

Each idea is scored on five axes: demo appeal (Demo), real value from weight learning (WL), how central Box and the skills are (Box), data feasibility (Data) and implementation risk (Risk, where L means lower risk). The scores are my judgment, not measurements.

| # | Idea | What the weights learn | Demo | WL | Box | Data | Risk | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | **Correction-trained router.** An agent uses Box MCP to find and read new files. A local LoRA model outputs `{doc_type, route_label, needs_review, evidence_span}`. App code maps `route_label` to a Box folder ID. Approved reviewer corrections become the next training rows. | A mapping from document text and extracted fields to the org's own taxonomy and routing conventions, with a quoted evidence span. It does not learn Box mechanics. | M-H | M | H | M-H | L | **Winner** (pragmatic) |
| 2 | **Contract-variance disposition triage.** The contract skill's cited variance list (`ai_qa_multi_file` against the template) goes to an adapter that suggests *escalate / likely-acceptable / needs-attorney* for each variance. | How the firm's attorneys dispose of each type of clause deviation at first review. | H | M-H | H | L-M | M-H | Ambitious #2 |
| 3 | **Skill-procedure distillation.** A small tool-calling model is trained on validated traces of the Box skills' procedures: resolve scope, read before write, confirm, verify. | A tool-sequencing policy given live tool schemas. It does not learn permissions or identity. | H | L-M | H | M (synthetic) | H | Ambitious #3 |
| 4 | **Extraction post-corrector.** Box AI extracts fields, reviewers fix them, and an adapter learns to rewrite the raw extraction into the org's canonical form. | Org conventions for interpreting fields, e.g. which date counts as "effective". | M | M | H | M | M | Viable alternative to #1 |
| 5 | **M&A request-to-data-room mapper.** Maps diligence request items to the firm's index folders, using past deals' placements as labels. | The firm's data-room index taxonomy. | M | M | M-H | L-M | M | Niche |
| 6 | **Diligence report writer in house style.** | Phrasing learned from approved reports. | M | L | M | L | M | Reject: a style guide plus few-shot examples is a strong baseline; comparable performance remains unmeasured |
| 7 | **TensorFold "org memory".** Teach facts such as "Acme's MSA owner is Dana" into Nemotron's weights. | Isolated facts stored in added neurons. | H (3D view) | L | L | H | H | Reject as the core. Hub Q&A or retrieval is better, and facts change |
| 8 | **Intake completeness checker.** | — | M | ~0 | H | — | L | Reject for explicit presence checks: rules are a strong baseline; semantic evidence sufficiency is a separate, untested task |

Notes on the rejections:
- **#8:** the intake skill already treats the checklist as firm-supplied input [code: `skills/box-legal-workflows-intake/SKILL.md`].
- **#7:** see TensorFold limits in §3.
- **#1, honest caveat:** for flat labels, an embedding classifier, such as logistic regression over embeddings (which also learns weights) may match or beat a LoRA LM. It must be a baseline arm. LoRA earns its place only if it wins on multi-field structured output, evidence spans, long-tail labels, or selective accuracy.

## 2. Top three expanded

### #1 Correction-trained router (winner)

**Demo.** A mixed "Inbox" folder in a Box sandbox. The agent:
1. calls `who_am_i`;
2. lists the folder;
3. reads each file with `get_file_content`;
4. optionally runs `ai_extract_structured_from_fields`.

The adapter then proposes a route and quotes its evidence. The reviewer UI shows suggestions under a confidence threshold, the reviewer corrects two of them, and the app appends the corrections to `corrections.jsonl`. A short `mlx_lm.lora --resume-adapter-file` run (time not measured) produces adapter v2. On a held-out, *later* batch, v2 fixes the same class of error. A dashboard shows adapter v1 against v2, the prompt baseline and the classifier baseline, and v2 can be rolled back.

**Trustworthy labels.**
- Reviewer-approved corrections logged locally, with reviewer ID, timestamp and the evidence they saw.
- Optional bootstrap: historical folder placement. These are weak labels: misfiles exist and placement is not policy, so a reviewer should audit a sample.
- Store labels as logical names. A versioned config maps names to Box IDs, so the model never emits IDs.

**Why weights might beat prompting or retrieval.**
- The taxonomy's boundaries are often tacit, e.g. "vendor SOW that references an MSA goes to Procurement, not Legal". Many corrections spread over many label pairs don't fit a short prompt.
- kNN retrieval of past corrections is the strongest prompt-side baseline and may win. That is an empirical question, not something to assume.
- Inference can be local; cost and latency depend on the chosen model, input and output lengths, and hardware, and were not measured.

**Leakage-free test.**
- Split by time, then group by client, matter and counterparty, so no group appears in both train and test.
- Near-duplicate dedup across splits (MinHash or embeddings). Templates make this essential.
- Strip filename and path tokens that encode the destination.
- Freeze the test set before any training.

**Retained behavior.**
- (a) Accuracy on classes that were *not* corrected in an update.
- (b) Fixed regression set from adapter v1.
- (c) Output-schema validity.
- (d) A small general-instruction probe, compared with the base model to catch broad drift. Retention must be measured for the actual adapter and task; this run did not read the cited forgetting paper beyond its search summary.

**Confidence.** Do not treat label-token probabilities as calibrated. Fit temperature or a threshold on validation data, and report expected calibration error (ECE) and selective accuracy against coverage on test.

**Comparison arms:** zero-shot base · few-shot prompt · kNN retrieval of corrections · embedding classifier · LoRA · LoRA + retrieval.

**Smallest hackathon slice.**
- 3–5 route labels and one inbox folder.
- Local corrections only, with no Box writes.
- Corpus: one that judges can see. A public contract set is an option, but I did not inspect its licence [unknown].

**Dependencies and blockers.**
- Box sandbox with MCP connected. `get_file_content`, `list_folder_content_by_folder_id`, search and `ai_extract_*` are listed as default **On** [doc]. Entitlements and Box AI availability are **[unknown]**.
- `move_file` and `set_file_metadata` are default **Off** [doc], so show the move as a proposal unless an admin enables it.
- An Apple-silicon Mac, or a CUDA machine running mlx-lm's CUDA extras [code: `pyproject.toml`; CUDA training itself unverified].
- A small model whose architecture mlx-lm implements (e.g. `models/qwen3.py`, `gemma3.py` exist) [code]. The exact model and its memory fit are **[unknown]**.

### #2 Contract-variance disposition triage

**Demo.** The contract skill produces a cited variance report. Each variance gets a predicted disposition and the closest past attorney disposition. Every final call stays with the attorney, as the skill requires [code: "Risk, materiality, and favorability are firm + attorney calls"].

**Labels.** Attorney disposition *at first review* of each variance, captured in the UI.
- Do **not** use final negotiated text as preference labels. It reflects leverage, deal size, counterparty and trade-offs, not house policy alone.
- Add those context features or exclude them.

**Why weights.** Dispositions depend on subtle clause wording against the template. A large, inconsistent set of precedents may be absorbed better in weights than in a context window. This is unproven.

**Test.**
- Hold out whole contracts and counterparties, and use a temporal split.
- Retained behavior: variance-extraction faithfulness and citation correctness unchanged.
- Score agreement with attorneys against inter-attorney agreement as a reference for label consistency, not a strict mathematical ceiling.

**Slice:** NDAs only, 3 dispositions.

**Blockers:** privileged data, label scarcity, legal sign-off, and the `ai_qa_multi_file` entitlement [unknown].

### #3 Skill-procedure distillation (ambitious)

**What's learned:** sequencing policy only. Schemas, permissions and identity stay explicit at runtime:
- the live `tools/list` output is in the prompt;
- the server enforces access;
- `who_am_i` is checked before any write.

The box-mcp skill itself says "runtime schemas govern names, inputs, and outputs" [code: `skills/box-mcp/SKILL.md`].

**Labels.** Traces from a teacher model running the full skills against a *mock* MCP server that replays the documented tool catalog. A validator keeps only traces whose end state matches the spec: read-back verified, confirmation before writes, full pagination. Tool-call training data is supported (`tools` JSONL) [doc+code: LORA.md, `tuner/datasets.py`].

**Required four-arm ablation:** {base, adapter} × {minimal instructions, full skill text}. Score with these held-out *compositions*, e.g. trained on search→extract and list→comment, tested on search→extract→comment→verify:
- end-state semantics;
- unsafe-write rate;
- use of tools not present in the catalog;
- recovery from injected 403, 409 and 429 errors.

JSON validity alone does not count.

**Risk.** Base model + full skill text may already win. Then the result is that distillation saves only context, which is still a legitimate finding.

## 3. Feasibility evidence

**Box operations**
- [Box MCP tools](https://docs.box.com/en/box-mcp/tools) [doc, "Last modified September 2, 2026"].
  - Default On: `who_am_i`, `get_file_content`, `list_folder_content_by_folder_id`, `search_files_keyword` and `search_files_metadata`, `ai_extract_structured_from_fields`, `ai_qa_single_file` and `ai_qa_multi_file`, `create_file_comment`, `upload_file`.
  - Default Off: `move_file`, `set_file_metadata`, `get_download_url`, `update_file_properties`, `create_collaboration`.
  - `ai_qa_single_file` processes only the first 1 MB of text.
- [Admin controls](https://docs.box.com/en/box-mcp/admin-controls) [doc]: per-integration custom configuration overrides the enterprise default; there are no per-user controls.
- The skills reference `ask_agent` and `list_custom_agents` [code: `box/references/ai-and-retrieval.md`], but neither appears on the tools page [doc]. Discover them at runtime.
- The skill's metadata reference URL `post-files-id-metadata-global-properties/` returned **HTTP 404** (doc drift).
- No live auth or calls were made, so availability is **[unknown]**.

**LoRA in mlx-lm** (HEAD `93e6d4a`) [code]
- Backward pass: `nn.value_and_grad` (`tuner/trainer.py:239`).
- Save: `mx.save_safetensors` of trainable params, written periodically and at the end (`trainer.py:370–380`).
- Resume: `--resume-adapter-file` → `load_weights(strict=False)` (`lora.py:257–259`).
- Reload for inference: `load(..., adapter_path=)` → `load_adapters` reads `adapter_config.json` and `adapters.safetensors` (`utils.py:648–697`, `tuner/utils.py:123–147`).
- QLoRA: automatic when the model is quantized; `QuantizedLinear` is wrapped (`tuner/lora.py:22`).
- Training types: `lora`, `dora`, `full`; `--mask-prompt`; `fuse` [doc: LORA.md].
- The doc's model-family list is not exhaustive relative to implemented modules [code]; file count alone does not establish trainable architecture count.
- The inspected default training path uses next-token loss, without a separate classification head [code inspection of `default_loss`]; this does not rule out custom training code.

**TensorFold Living Weights** (HEAD `6ee828c`; `docs/living-weights.md` unchanged since `b090e3b`)
- It refuses every model family except Nemotron (`zig/src/native/metal.zig:535` test name) [code].
- Model: Nemotron 3.5 Lightning 30B-A3B MLX 4-bit, an 18.5 GB checkpoint; teach a copy [doc].
- Pocket: 64 added neurons at each MoE layer; a fact uses about 10 neurons across selected layers, rather than 10 at every layer (`families/nemotron/pocket.zig:24–25`) [code]. Base weights are not changed [doc].
- Hardware: CUDA learning only on GB10 / sm_121 (`native/cuda.zig:291`) [code]. The doc names M5 Ultra and M3 Ultra as tested Macs [doc].
- Speed and recall:
  - 1.5–3 minutes per fact;
  - 21-fact handbook: "kept about half the facts and answered 6 of 16", and answers about unstated things got worse;
  - 6-fact handbook: 3–6 of 6, with cross-role leakage;
  - a question must name the subject;
  - extra facts slow decoding (about 16% at 21 facts) [doc].
- Deletion and rollback exist [doc].
- Text is split into facts by a fact finder (`server/slide_found.zig`) [code].
- `--learn` and `--learn-conversations` store prompt state; they are **not** weight learning [doc: README, api.md].
- So TensorFold does single-fact insertion. It is not workflow or classification learning.

**Box Extract "learning from corrections".** A search snippet claimed "Automated AI refinement — coming soon". A fetch of box.com/extract did **not** show that text. Status **[unknown]**. If Box ships it, it becomes a strong baseline for #4.

## 4. Recommendation

**Build #1, with #4's post-correction as a stretch.** Reasons:
- Labels come from a loop you own: local reviewer UI corrections. You don't need Box write entitlements.
- The required Box operations are documented as default-On.
- mlx-lm's train, save, resume and reload path is verified in code.
- The test can falsify the claim honestly, because classifier and retrieval arms are built in.

**Unknowns that could change this:**
1. Whether a labeled or seed corpus exists. Without one, #3 on synthetic traces becomes more practical.
2. The judging rubric. "Wow" favors #2 or #3; "useful" favors #1.
3. Hardware, which sets model size and turnaround.
4. Box AI and MCP entitlements in the sandbox.
5. Whether the embedding classifier ties LoRA. If it does, report that. Evidence spans and multi-field outputs are only a remaining advantage if a separate evaluation demonstrates one.

Use TensorFold only as an optional side demo of fact insertion, with its documented limits on screen.

## 5. Tools and evidence summary

- **Cloned to `research/src/`:**
  - box/skills `84320fd8984b95cab430335cd341d8314c14bbcb`
  - ml-explore/mlx-lm `93e6d4a6447b3080861985947f0820e76fcb957d`
  - ashhart/TensorFold `6ee828c24bf802cdd73507d6fc60bb27a82c0d66`; the pinned `b090e3b` was diffed and its docs read
- **Downloaded to `research/web/`:** `box-mcp-tools.html`, `box-mcp-tools.txt` (extracted text), `box-mcp-admin.html`.
- **URL status checks:** `research/notes/url-status.txt`. An HTTP 200 only means the page exists, not that its content was read.
- **WebFetch:** docs.box.com admin-controls, box.com/extract.
- **WebSearch:** Box Extract corrections; arXiv 2405.09673; arXiv 2209.11055. These were search summaries only; I did not read the papers.
- **Commands:** git clone, rev-parse and diff; grep, sed and wc over the sources; curl for docs; one isolated `python3 -I` HTML-to-text step.
- **Failures:** one `grep --include` glob error under zsh, retried; the 404 above. No permission denials.
- **Not verified:** Box auth or runtime tool lists, Box AI behavior, any training run or timing, model memory fit, TensorFold runs, dataset licences.


## Scratch cleanup

After the completed run, Codex verified the three disposable repository snapshots were clean, each had only its own worktree, and no process held files under the run directory. The task-owned `/private/tmp/box-learning-opus55-research-wh_gmx0z` directory was removed. Its paths above describe the research session; retained evidence is this report, the pinned public revisions and source links.
