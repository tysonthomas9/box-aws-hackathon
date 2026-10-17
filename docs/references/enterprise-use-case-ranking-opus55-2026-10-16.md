# Enterprise use cases for a Box-skills + persistent-weight-learning POC: business value vs. learning value

> Supervisor review: This is the completed Opus 5.5 report, preserved with a review note. Interpret categorical claims such as “no category” as **not found in the sources reviewed**, rather than an exhaustive literature finding. Claims that RAG or rules dominate all HR/RFP/scoping tasks are hypotheses; the cited knowledge-injection work does not settle every behavioral-learning use case. Some sources were only snippets or abstracts and are labeled below. The parent did not adopt those as verified business outcomes.
>
> Independent checks confirmed Meta’s training/backtest description, ByteDance’s LoRA mechanism and 0.849→0.862 F1 comparison on 160 later tickets, and TeleDoCTR’s result in which retrieved demonstrations beat the fine-tuned report on LLM-judged root-cause accuracy. Fin’s current page documents trained models but also changes the base model between versions; gains are not a training-only ablation. No public evidence reviewed establishes that a few corrections will yield useful continual customer-specific adaptation.
>
> Maintenance ranks well as an offline candidate, conditional on dataset license, actual access, representative labels and a defensible split. This run did not verify those prerequisites or local training feasibility. Proposed numerical kill thresholds are experiment-design suggestions, not established performance requirements. Read the [combined synthesis](enterprise-learning-ranking-and-funding-2026-10-16.md) alongside the [independent funding research](enterprise-startup-funding-jul16-oct16-2026.md).


*Research date: 2026-10-16 (America/Los_Angeles). Public sources only. No accounts, data, models or customers were accessed. Funding is deliberately excluded; a separate track covers it.*

## 1. Bottom line

- **No category has public, controlled evidence that customer-specific *continual* weight updates beat strong instructions + RAG + an ordinary classifier on a business metric.** The strongest evidence is one-time supervised fine-tuning on historical, outcome-labeled records, compared against zero-/few-shot prompting, and sometimes against retrieval/ICL.
- **Best learning fit:** repeated diagnostic mappings with natural outcome labels — *symptom → root cause / corrective action / routing*. IT incidents and maintenance/field-service logs have the most direct primary technical evidence ([Meta](https://engineering.fb.com/2024/06/24/data-infrastructure/leveraging-ai-for-efficient-incident-response/), [Microsoft ICSE'23](https://ar5iv.labs.arxiv.org/html/2301.03797), [ByteDance](https://arxiv.org/html/2504.08475v1), [Nokia/TeleDoCTR](https://arxiv.org/html/2601.00691v1), [Hitachi/MaintNet](https://papers.phmsociety.org/index.php/phmap/article/download/4652/phmap_25_4652)).
- **Best business-outcome evidence for a trained system:** technical customer support. A deployed assistant fine-tuned on outcome-labeled conversations, weighted toward top performers, raised resolutions/hour ~14% across 5,179 agents in a staggered rollout ([NBER w31161](https://www.nber.org/papers/w31161); [paper text](https://ar5iv.labs.arxiv.org/html/2304.11771)). But it was compared with *no tool*, not with RAG. Competition here is also the most intense, and vendors already post-train on pooled data ([Fin Apex](https://ideas.fin.ai/p/fin-apex-1-0-model-announcement), [Fin models](https://fin.ai/cx-models)).
- **Weak fits for weight learning:** RFP/security questionnaires and HR service, where facts change and approved evidence matters. Rules + curated RAG dominate there. IAG's HR deflection gain was attributed to rewriting ~730 KB articles, not to training ([iTnews](https://www.itnews.com.au/news/iag-builds-ai-into-its-hr-service-delivery-628474)).
- **TensorFold Living Weights does not demonstrate workflow learning.** Its docs describe discrete fact insertion only, with fragile updates and capacity limits ([docs](https://github.com/ashhart/TensorFold/blob/main/docs/living-weights.md), [issue #678](https://github.com/ashhart/TensorFold/issues/678)). It fits "remember this fact", which is the job RAG already does better ([Ovadia et al., EMNLP'24](https://aclanthology.org/2024.emnlp-main.15); [Gekhman et al., EMNLP'24](https://aclanthology.org/2024.emnlp-main.444)).
- **Recommended shortlist:** (1) IT incident triage/resolution apprentice, (2) maintenance/field-service corrective-action apprentice, (3) technical-support escalation/troubleshooting apprentice. Whether learning helps at all is **unestablished** for this POC until a held-out comparison against a strong baseline is run.

## 2. Evidence tiers used

| Tier | Meaning |
|---|---|
| **T1** | Controlled comparative training evidence on the task: fine-tuned vs. non-trained baseline, held-out/temporal test |
| **T1−** | Same as T1, but the baseline is weak (no RAG/ICL), metrics are lexical only, or the source is vendor self-report |
| **T2** | Documented training mechanism, but no comparable business outcome |
| **T3** | Plausible hypothesis only |
| **W** | Weak fit: rules/RAG/classifier likely dominate |

"Business outcome" evidence is tagged separately: **[ind]** = independent/academic measurement; **[vend]** = vendor or customer self-report; **[survey]** = vendor-run survey.

## 3. Category evidence

### 3.1 IT support / incident resolution (CIO, ITSM, SRE)
- **Task & frequency:** High-frequency, recurring diagnosis: incident → likely cause, runbook step, owning team. Postmortems and resolution notes accumulate continuously.
- **Demand/ROI:** Moveworks markets 256% three-year ROI from a Forrester TEI. That figure models a *composite* organization, and the page's other customer figures carry no methodology [vend] ([Moveworks](https://www.moveworks.com/us/en/solutions/self-service)). ByteDance's deployed escalation system reports a 39% MTTR reduction and roughly ten person-days/day saved, extrapolated from 100 tickets [vend/academic, single company] ([arXiv 2504.08475](https://arxiv.org/html/2504.08475v1)).
- **Technical evidence (T1/T1−, best of any category):**
  - **Meta:** Llama 2 7B with continued pretraining plus two SFT stages on ~5,000 RCA examples. Labels were known root causes. In backtests restricted to information available when each investigation began, the root cause was in the top 5 for 42% of investigations. No held-out split is described, and there is no RAG-only comparison ([Meta engineering, 2024-06-24](https://engineering.fb.com/2024/06/24/data-infrastructure/leveraging-ai-for-efficient-incident-response/)).
  - **Microsoft:** 40k+ incidents, temporally ordered. Fine-tuning roughly doubled or tripled lexical metrics over zero-shot GPT-3.x, e.g. mitigation ROUGE-L 2.31 → 10.22. Incident-owner ratings were modest (~70% gave ≥3/5). The 2022-era zero-shot baseline is weak by today's standards ([ar5iv](https://ar5iv.labs.arxiv.org/html/2301.03797)).
  - **ByteDance:** LoRA SFT with label-consistent CoT augmentation. On a time-based split, F1 was 0.862, vs. 0.849 for CoT + retrieved ICL and 0.801 for the best BERT classifier. This gain over a strong baseline is **small**, on a 160-ticket test set ([arXiv](https://arxiv.org/html/2504.08475v1)).
  - **Nokia TeleDoCTR:** QLoRA routing reached 80.3% accuracy vs. 79.6% for fine-tuned BERT, again a *slight* gain. The fine-tuned generator beat RAG on reference metrics, but an LLM judge rated RAG higher on accuracy (3.33 vs. 2.56) ([arXiv 2601.00691](https://arxiv.org/html/2601.00691v1)).
- **Ordinary-classifier baseline exists in-product:** ServiceNow Predictive Intelligence trains per-instance classifiers on historical records for category/assignment group. Its own community notes that it struggles with sparse or overlapping groups. This rests on search snippets, not full pages ([ServiceNow docs](https://www.servicenow.com/docs/r/XRgEFx7nPN6ciT_BBIvnbg/F6pVApV4UwxXH3JIg9KRpQ), [community](https://www.servicenow.com/community/servicenow-otto-articles/multi-method-assignment-group-prediction-with-now-assist/ta-p/3562536)).
- **Takeaway:** Weight learning helps most on *ranking/diagnosis over org-specific signals*. It helps marginally on routing once a fine-tuned classifier or retrieved ICL exists.

### 3.2 Technical customer support (VP Support)
- **Demand/ROI:**
  - Brynjolfsson/Li/Raymond: staggered rollout across 5,179 agents and ~3M chats at a Fortune 500 software firm. Resolutions/hour rose ~14%, and ~34% for novices [ind, quasi-experimental]. The tool was a GPT model fine-tuned on outcome-labeled conversations, with top performers flagged, plus an RLHF-like step. Agents followed suggestions only ~35–38% of the time ([NBER](https://www.nber.org/papers/w31161), [paper](https://ar5iv.labs.arxiv.org/html/2304.11771)).
  - Box reports >50% self-service answers across >10,000 questions/year and >1,000 hours saved. No method or dates are given [vend] ([Box blog](https://blog.box.com/how-box-uses-box-ai-transform-customer-support-sales-and-services)).
- **Technical evidence (T1− for the vendor-pooled model, T3 for per-customer continual learning):** Intercom post-trains Fin Apex on pooled, de-identified interactions. It claims gains over frontier models and one customer going from 68% to 75% resolution, with no A/B design disclosed [vend] ([Fin](https://ideas.fin.ai/p/fin-apex-1-0-model-announcement), [cx-models](https://fin.ai/cx-models)). A podcast summary attributes most of Fin's 30% → ~70% resolution climb to retrieval/reranking systems rather than the core LLM. This is a secondary source, not verified with Intercom primary text ([podcast notes](https://www.cognitiverevolution.ai/the-customer-service-revolution-building-fin-with-eoghan-mccabe-fergal-reid-of-intercom/)).
- **Takeaway:** Training on *expert-behavior traces with outcome labels* has a real-world signal. But the moat sits with vendors that have cross-customer data, and the key comparison (vs. RAG over the same knowledge base) is unpublished.

### 3.3 Professional-services scoping/estimating (Head of Delivery)
- **Demand:** Box reports SOW creation time down 35% and 2,000 hours saved across >1,100 SOWs. The workflow is *extraction + Doc Gen + human review*, with no learning involved [vend] ([Box blog](https://blog.box.com/how-box-uses-box-ai-transform-customer-support-sales-and-services)).
- **Technical evidence (T3/W):** In story-point research, zero-shot LLMs beat supervised DL models trained on 80% of project data, and few-shot improves further (abstract only; [arXiv 2603.06276](https://arxiv.org/abs/2603.06276)). Labels (actual effort vs. estimate) are sparse, delayed, confounded by staffing and scope change, and few per firm.
- **Takeaway:** High value, poor learning fit. Retrieval of similar past SOWs, templates and calibrated ranges likely dominates.

### 3.4 Manufacturing quality / field service (VP Quality, Service Ops)
- **Demand evidence:** Thin in what I inspected. Owens Corning's Box R&D archive and safety analytics stories contain **no metrics or methodology** ([Box blog](https://blog.box.com/owens-corning-turned-85-years-lab-notebooks-ai-powered-knowledge-base)). Plausible value drivers (repeat failures, first-time fix rate, scrap) were not quantified from primary sources in this run.
- **Technical evidence (T1−):** Hitachi America benchmarked LLMs on MaintNet aviation logs (problem → corrective action):
  - Fine-tuned 3–4B open models improved BLEU by up to ~90% and ROUGE-2 by ~30%.
  - Fine-tuned Gemma-3-4B surpassed GPT-4o on several lexical metrics, while GPT-4o kept the strongest semantic scores in prompting.
  - Gains scaled with training-split size.
  - Caveats: ratio-based random splits (not temporal or held-out-aircraft), lexical/semantic similarity only, no RAG baseline, no technician validation. Text extracted locally from the PDF; [PHM Society 2025](https://papers.phmsociety.org/index.php/phmap/article/download/4652/phmap_25_4652).
- **Data:** MaintNet is described as an open-source maintenance-logbook library covering aviation, automotive and facility domains ([COLING'20 demo](https://aclanthology.org/2020.coling-demos.2)). I did not verify its license. The aviation set is small (~6k records per a derived listing).
- **Takeaway:** Terse, abbreviation-heavy domain language plus naturally paired problem/action labels is exactly where small-model adaptation helps. "Action taken" is not the same as "validated fix", though.

### 3.5 Sales engineering / RFP / security questionnaires (SalesEng, RevOps)
- **Demand:** Loopio/APMP 2026 survey of 1,533 companies [survey]: ~166 RFPs/year; ~79% used genAI. The 33-hours-per-RFP and 39% win-rate figures came via secondary pages and were **not verified** against the PDF ([Loopio report](https://link.loopio.com/hubfs/Content%20Pieces/FY26%20Trends%20Report/trends-report-2026-digital-Master.pdf)). Vanta estimates 2–4 hours per security questionnaire, with no guarantee [vend; snippet] ([Vanta](https://vanta.com/automation-value-calculator)).
- **Learning fit (W):** Answers must cite *current, approved* evidence. Facts in weights go stale and risk hallucination ([Gekhman](https://aclanthology.org/2024.emnlp-main.444)). RAG beats unsupervised fine-tuning for knowledge injection ([Ovadia](https://aclanthology.org/2024.emnlp-main.15)). Weights could plausibly learn tone or answer-length conventions, which is low incremental value.

### 3.6 Finance shared-services exceptions (FinanceOps)
- **Demand:** AP benchmarks circulating (exception rate ~9% best vs. ~22% average; cost/invoice ~$2.78 best-in-class) are vendor restatements of an Ardent Partners report that disagree with each other. I treat them as unverified ([WEX](https://www.wexinc.com/resources/blog/what-does-it-cost-to-process-an-invoice-ap-benchmarks-every-finance-team-should-know/)).
- **Technical evidence (T2):** Per-customer learning *already exists* as ordinary ML. SAP Cash Application trains on historical clearing decisions, retrains periodically, and auto-clears above a confidence threshold. This rests on search snippets only; the fetched SAP Learning page returned 404 ([SAP Learning](https://learning.sap.com/courses/managing-cash-application-for-fi-ca/outlining-the-cash-application-add-on-for-financials-contract-accounting), [SAP blog 2017](https://blogs.sap.com/2017/08/24/ever-thought-about-machine-learning-in-finance-for-wholesale-distribution-2/)). Ramp fine-tuned an *embedding* model with triplet loss for merchant similarity; that post's content was not retrievable in this run, so only the search snippet supports it ([Ramp](https://engineering.ramp.com/transaction-embeddings)).
- **Takeaway:** Representation learning is valuable, but the classifier baseline is strong and entrenched. LLM weight updates add value mainly on free-text exception *explanations*, which remains unproven.

### 3.7 HR employee service (HROps)
- **Evidence:** At IAG, Now Assist deflection was 67% in the first month vs. 30% for the prior chatbot, with gains tied to knowledge-base restructuring and AU/NZ separation [vend/customer at vendor event] ([iTnews, 2026-09-04](https://www.itnews.com.au/news/iag-builds-ai-into-its-hr-service-delivery-628474)).
- **Learning fit (W):** Jurisdiction-specific, changing policy facts plus sensitive data mean RAG + workflow rules dominate.

### 3.8 R&D research reuse (R&D leadership)
- **Evidence:** Owens Corning's digitized notebooks are retrieval with anecdotal time savings and no metrics. A separate *predictive* use is well evidenced: fine-tuned GPT-3 matched or beat dedicated ML on chemistry/materials property tasks, especially in low-data settings (T1 for representation learning; [Jablonka et al., Nat. Mach. Intell. 2024](https://www.epfl.ch/labs/lsmo/leveraging-large-language-models-for-predictive-chemistry/); abstract/lab page only).
- **Takeaway:** "Search my archive" fits RAG. "Predict an experimental outcome from my lab's history" is a strong learning fit, but it is a scientific-ML product with specialized competitors and needs clean outcome tables, which notebooks rarely provide.

### 3.9 Optional / controls
- **Marketing/content:** Style adaptation is a known fine-tuning strength, but business value is diffuse and competition extreme. Not researched in depth.
- **Legal (control):** OpenAI's RFT case list reports Harvey's verbatim-passage extraction F1 rising from 0.563 to 0.677 [vend] ([OpenAI RFT use cases](https://developers.openai.com/api/docs/guides/rft-use-cases)).
- **Stronger case surfaced:** Clinical coding. Ambience's RFT model scored 0.57 vs. 0.39 base and 0.45 for physicians [vend]. Audited, gradable labels make it a better *learning* case than most of the list, but it is regulated and Box's role there is weaker.

## 4. Rankings (ordinal 1–5; judgment, not measurement)

BV = business value. LV = incremental learning value over strong prompting + RAG + classifier. FS = POC feasibility with no data or customers. Conf = evidence confidence.

| Category | BV | LV | FS | Conf (BV / LV) | Learning-evidence tier |
|---|---|---|---|---|---|
| IT incident triage/resolution | 4 | **4** | 3 | M / **M-H** | T1/T1− (Meta, MSFT, ByteDance, Nokia) |
| Maintenance/field-service corrective action | 4 | **4** | **4** | L / M | T1− (Hitachi/MaintNet) |
| Technical customer support | **5** | 3 | 3 | **H** / M | T1− business outcome; T3 per-customer continual |
| Finance exceptions | 4 | 3 | 2 | L / M | T2 (classical ML entrenched) |
| R&D research reuse (predictive subset) | 3 | 3 (search: 1) | 3 | L / M | T1 representation (chemistry) |
| Professional-services scoping | 4 | 2 | 2 | L / L | T3/W |
| Sales eng / RFP / security questionnaires | 4 | 1 | **5** | M / M | W |
| HR employee service | 3 | 1 | 3 | L / M | W |
| Marketing content | 2 | 2 | 4 | L / L | not researched |

**Combined shortlist:** IT incident ≈ maintenance/field service > technical support > finance exceptions. Maintenance ranks first on *feasibility* because a public problem→action dataset exists. IT ranks first on *learning evidence*. Support ranks first on *business-value evidence*.

**Sensitivity:**
- **Training-data access:** If the team gets an enterprise's historical ITSM export (incidents + resolution codes + postmortems), IT moves clearly to #1. If no partner data materializes, maintenance (public logs) is the only honest offline demo. Support needs public forum/QA data, where outcome labels are weak (accepted answers ≠ resolution).
- **Customer access:** Finance exceptions rises to the top-3 *only* with an ERP partner, since the labels sit in clearing history.
- **Competition:** Support faces Intercom, Zendesk, Sierra and Decagon, which have pooled-data post-training. IT faces ServiceNow, Moveworks and incident-tooling vendors. Maintenance/field service is less saturated by LLM-native players, but I did not verify that rigorously.
- **Platform risk:** OpenAI's self-serve fine-tuning is closing to new users. As of 2026-05-07, organizations without prior fine-tuning cannot create jobs, and all new jobs end 2027-01-06 ([deprecations](https://developers.openai.com/api/docs/deprecations)). This favors open-weight local LoRA, e.g. `mlx_lm.lora`, which supports LoRA/QLoRA/DoRA/full fine-tuning ([mlx-lm LORA.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)).

## 5. Top three, expanded

### 5.1 IT incident triage & resolution apprentice
- **Workflow/demo:** A new incident (title, symptoms, service, recent changes) produces a ranked list of likely root-cause categories and the next runbook step, each with a cited runbook or postmortem from Box.
- **Box's role:** Box holds the runbooks and postmortems and enforces permissions. Incident records live in the ITSM system (separate integration). Box skills encode the *procedure* (gather evidence, cite, escalate); weights learn the *mapping*.
- **What parameters learn:** A representation from org-specific symptom vocabulary to resolution classes and steps. This is a decision policy, not facts.
- **Labels:** Resolution codes, assignment groups and postmortem root causes. Quality caveats: noisy, often reassigned, and "closed" ≠ fixed. Use only incidents with postmortems or confirmed resolution for the gold set.
- **Buyer/case:** CIO/VP IT Ops. Metrics are MTTR, reassignment ("ping-pong") count, and engineer minutes per incident. Vendor ROI claims do not transfer.
- **Competitors:** ServiceNow (Now Assist + Predictive Intelligence), Moveworks, PagerDuty/incident tools.
- **Differentiation (credible only if measured):** Org-specific adaptation of an open, local model, with permission-aware citations from Box.
- **Strong baseline:** Frontier/open model + Box skill + retrieval of the top-k similar past incidents as ICL + a fine-tuned BERT/logistic classifier for routing. ByteDance shows this baseline comes within ~1 F1 point of SFT.
- **Leakage-free eval:**
  - Temporal split.
  - Held-out *services* and held-out *new failure modes*.
  - Dedupe near-duplicate tickets across splits.
  - Strip resolution text from inputs.
  - Test *compositions*: a known symptom on an unseen service.
- **Business metric:** top-k root-cause hit rate, simulated reviewer minutes to accept/correct, and wrong-confident rate at a fixed coverage threshold.
- **Kill condition:** LoRA ≤ baseline + 2 points top-3 accuracy on held-out services, or a worse wrong-confident rate.
- **Smallest honest POC:** Requires a design-partner export of a few thousand resolved incidents. Without one, publicly posted postmortems can support only a qualitative demo, not a learning claim (label quality unverified).

### 5.2 Maintenance / field-service corrective-action apprentice
- **Workflow/demo:** A technician's terse problem note produces a ranked set of corrective actions plus the manual section (Box) and a "requires inspection" flag. CMMS/MES actions stay outside Box.
- **What parameters learn:** Abbreviation-heavy domain language and a problem→action mapping.
- **Labels:** The recorded action taken (MaintNet). This is not a validated fix; repeat-failure follow-up is the better label when available.
- **Buyer/case:** VP Quality/Service. Candidate metrics are first-time-fix rate, repeat visits and technician diagnostic time; none were quantified from primary sources here.
- **Competitors:** CMMS/field-service vendors' AI assistants; not deeply surveyed.
- **Strong baseline:** GPT-class model + few-shot retrieval of similar logs. The Hitachi paper shows few-shot narrows the gap substantially.
- **Eval:**
  - Split by aircraft/asset or by time, not randomly (the paper used random ratio splits).
  - Hold out component families.
  - Score action-class accuracy after normalizing actions into canonical classes, not just BLEU.
- **Kill condition:** Fine-tuned small model ≤ retrieval-ICL baseline on held-out assets.
- **Smallest honest POC:** MaintNet aviation subset (verify license) → `mlx_lm.lora` QLoRA on a small open model vs. RAG-ICL on the same model vs. a TF-IDF/logistic classifier, using an asset-held-out split. This is feasible offline, and the result is a dataset-level claim, not proof of continual adaptation.

### 5.3 Technical-support escalation & troubleshooting apprentice
- **Workflow/demo:** A complex ticket produces a decision to escalate or not, plus next diagnostic step(s) citing Box KB articles. The demo targets agent assist, *not* customer-facing deflection, where incumbents are strong.
- **What parameters learn:** The expert troubleshooting policy, distilled from resolved, high-CSAT tickets (Brynjolfsson-style top-performer weighting).
- **Labels:** Resolution outcome, escalation correctness (ByteDance-style analyst feedback), and handle time. These are biased toward agents who already performed well; feedback coverage was 472 of 2,012 in ByteDance.
- **Strong baseline:** The same model + Box KB RAG + retrieved resolved-ticket exemplars + procedure skill.
- **Eval:**
  - Temporal split.
  - Held-out products/versions.
  - Held-out *composite* issues (two known symptoms co-occurring).
  - Measure suggestions accepted unedited and reviewer edit distance/minutes.
- **Kill condition:** No lift over the ICL baseline on held-out products. A second kill condition: lift disappears after the KB is updated, which would mean the weights memorized facts that RAG should supply.
- **Smallest honest POC:** Needs a partner's resolved-ticket history. Public Q&A forums give weak labels and are acceptable only as a pipeline dry-run.

**Across all three:** One correction should never be presented as generalization. Report learning curves (n = 50/200/1,000 labeled cases), variance across seeds, and forgetting on a frozen general-capability probe. LoRA forgets less than full fine-tuning, but it also learns less ([Biderman et al., TMLR'24](https://mlanthology.org/tmlr/2024/biderman2024tmlr-lora)).

## 6. Which learning mechanism fits each case

| Category | Best-matching mechanism | Note |
|---|---|---|
| IT incident | Representation/classification + ranking (SFT/LoRA; ranker fine-tuning) | Online preference updates are possible where accept/reject signals exist |
| Maintenance/field service | Representation (domain language) + SFT; distillation to a small local model for cost | |
| Technical support | Broad repeated expert procedures (SFT on top-performer traces; RFT if a gradable outcome exists) | |
| Finance exceptions | Classical classifier/embeddings first; LLM SFT for explanation text | |
| R&D predictive | Representation/regression fine-tuning | |
| RFP / HR / prof. services | Mostly RAG + rules | Weights for style only |
| TensorFold Living Weights | Factual memory only | Best match is "remember a user/company fact", which is not the target here |

**Options beyond LoRA:**
- **Online RL from implicit accept/reject.** Cursor's Tab model ships new checkpoints every ~1.5–2 hours from accept/reject rewards, with 21% fewer suggestions and a 28% higher accept rate. This is the clearest public example of genuine continual weight updates from usage, but it relies on 400M requests/day [vend] ([Cursor](https://cursor.com/blog/tab-rl)).
- **RFT with graders,** where experts agree on answers. OpenAI's docs warn about reward hacking and say RFT cannot bootstrap from a 0% success rate ([RFT guide](https://developers.openai.com/api/docs/guides/reinforcement-fine-tuning)).
- **Fine-tuned retrievers/rerankers,** where Intercom reportedly found most of its gains (secondary source).

**The requested POC constraint:** Saving a SKILL.md, retrieving cases or prompting does *not* count as the learning demonstration. They are mandatory baselines. The honest POC is: periodic LoRA/QLoRA consolidation of accumulated, validated cases into adapter weights, versioned with rollback, with RAG still supplying changing facts.

## 7. TensorFold Living Weights: current primary-doc status (verified 2026-10-16)

- **Scope:** Experimental. Only the Nemotron 3.5 Lightning MLX 4-bit checkpoint is supported. Each MoE shared expert gets a 64-neuron pocket, and a fact uses ~10 neurons. The model generates its own training Q&A, and held-out wording checks gate each lesson ([docs](https://github.com/ashhart/TensorFold/blob/main/docs/living-weights.md)).
- **Measured results:**
  - Six-fact handbook: 3–6 of 6 answers correct across 6 runs.
  - 21-fact handbook: ~half the facts kept, 6 of 16 questions answered.
  - Ten facts about one company degraded unrelated answers.
  - ~1.5–3 minutes per fact.
- **Update and forgetting behavior:** Fact updates and deletions are fragile; deleting one fact broke a dated fact in a four-fact test. The authors call their measurements "not a rate" ([issue #678](https://github.com/ashhart/TensorFold/issues/678)). Undo arrived in 1.0.12 on 16 Oct ([releases](https://github.com/ashhart/TensorFold/releases)).
- **Verdict:** No primary doc claims procedure, diagnostic or workflow learning. Using it for "apprentice" demos would overclaim.

## 8. Method, tools and limits

- **Tools:** WebSearch (~25 queries, standard mode) and WebFetch on ~35 pages. One PDF (Hitachi PHM'25) was text-extracted locally with a stdlib-only Python script (`research/scripts/pdftext.py`, run with `python3 -I`) and searched with `rg`; the scratch copy is in `research/scratch_phm/`. The Brynjolfsson PDF was copied to `research/scratch_pdf/` but read via its ar5iv HTML instead. Scratch files are left in place for the supervisor.
- **Read via abstract or summary only:**
  - Ovadia, Gekhman, Biderman, LoRA Land ([arXiv 2405.00732](https://arxiv.org/abs/2405.00732): 310 QLoRA models averaged +10 points over GPT-4 on narrow tasks).
  - Jablonka, story-point papers, SAP pages.
  - The Loopio PDF was not opened.
- **Snippet-only:** ServiceNow, SAP, Vanta, Loopio and Ramp claims came from search snippets, and the Intercom podcast is a secondary source.
- **Not inspected:** The Dell'Acqua/BCG consulting experiment (HBS/SSRN returned 403), so it is not cited. Ramp's engineering post content was not retrieved.
- **Fetch method:** WebFetch summarizes pages with a small model, so specific numbers were cross-checked where possible but may contain extraction errors. Vendor numbers are labeled as such and must not be transplanted to this product.
- **Not done:** No pricing or TAM was estimated. No model was trained or downloaded.


## Supervisor run verification

Model initialization and final usage identify `claude-opus-5-5`; 25 WebSearch and 36 WebFetch tool calls were observed. All default built-in tools were available, with normal automatic permission checks; external MCP servers were not connected. Web tooling also recorded internal `claude-haiku-5-5` usage. There was no main-model fallback, no spawned Claude subagents, no permission denials and no safety stops. Session `08f131cd-a8eb-424f-bac2-21e91792d2c1` completed successfully in 74 turns. CLI-reported total usage cost was $2.1993245 at list-price equivalents, not a verified additional subscription charge. One Bash call failed with no output; the report was still written and completed.

The [run metadata](enterprise-opus55-ranking-evidence-2026-10-16/run-metadata.json), original report, prompt and complete tool event log are retained in the sibling evidence directory. Public PDFs and extraction scratch copies were disposable. No model checkpoint or package was downloaded or installed.

Scratch cleanup: `/private/tmp/enterprise-opus55-ranking-bjppqshx` was removed after run completion, ownership/inventory checks, no open handles or Git worktrees, and hash-verified preservation of the report and tool trace. Its absence was verified.
