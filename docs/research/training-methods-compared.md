Research date: 2026-10-16. Sources: Intercom Fin Apex launch post and fin.ai/cx-models; Harvey "Post-training RLM agents for M&A diligence"; TickIt paper (arXiv 2504.08475v1); TensorFold docs/living-weights.md at b090e3b (local checkout) plus the Nemotron/TensorFold reference note.

| | Intercom Fin | Harvey RLM | ByteDance TickIt | TensorFold Living Weights |
|---|---|---|---|---|
| What learns | Apex answer model (base not named); a fine-tuned 14B summarizer; ModernBERT escalation router and feedback parser | Only the root orchestrator (Qwen3.5-122B-A10B; LoRA on GLM-5.3 run). Sub-agents frozen | Doubao-Pro-32k via LoRA (rank 32, alpha 32, lr 5e-5, 10 epochs, batch 1) | 64 added neurons per shared MoE expert in Nemotron 3.5 Lightning 4-bit; base frozen |
| Training signal | Not disclosed. "Post-training" on de-identified past Fin interactions | Non-verifiable made scorable: LLM judge grades memo against expert rubric of hundreds of pass/fail criteria; reward = pass rate | Category labels from analyst feedback (upvote, downvote, redirect click) plus 148 hand-labeled tickets | The fact itself. Model writes its own lesson: ~12 questions, answers with the fact in view, near misses to leave alone |
| Method | Not disclosed | GRPO (group 8, batch 24), hour-long rollouts; also rejection-sampling self-distillation SFT on GLM-5.2 | Model-generated chain-of-thought revised to match the label ("Correct and Revised"), then SFT. Periodic batch retrain, not online | Fit neuron inputs with Adam + squared hinge (fire on fact questions, zero elsewhere); fit outputs by backprop on answers plus preservation examples |
| Data scale | "Millions of support interactions" | Synthetic data rooms up to 5,000 docs / 80M tokens; 50 held-out rooms | 460 training tickets, 160 test | One fact per lesson, 1.5 to 3 min each |
| Gate / eval | Proprietary evals; "confirmed resolutions", hallucination rate | Held-out rooms, rubric pass rate | F1 on test tickets; both old and new model ran live | Held-out wordings, near misses, unrelated prompts; lesson removed whole if any fail |
| Reported result | 68% to 75% resolution at one customer; Apex 2.0 +8.6% confirmed resolutions vs 1.0 (base model also changed) | 29.9% to 63.0% rubric pass rate | F1 0.862 SFT vs 0.849 retrieved-example prompting; MTTR down 39% (not isolated to fine-tuning) | 21-fact handbook: 6 of 16 answered; worse answers on unstated topics |
| What it does not show | Recipe, ablation vs strong prompting | Who wrote rubrics, reward-hacking controls, deployed ROI | Large gain over strong prompting | Learning behaviour or procedures |

## Takeaways for the POC
- TickIt is the closest template: reviewer clicks become labels, model writes a rationale constrained to the label, LoRA SFT, periodic retrain, old and new versions compared.
- Harvey shows the non-verifiable route: rubric + LLM judge. GRPO is out of reach on a Mac, but its rejection-sampling SFT variant (sample several answers, judge-score, train on the best) is feasible.
- TensorFold inserts discrete facts, not diagnostic policy. At most a side demo.
- Intercom proves business value of domain post-training but publishes no reproducible recipe.


## TensorFold Living Weights: deep dive (local checkout b090e3b, docs/living-weights.md + zig/src)

**Pipeline per fact (1.5 to 3 min on M3/M5 Ultra):**
1. Fact found in text ("chat" first-person fact vs document fact).
2. Model writes its own lesson (server/slide_lesson.zig): ~12 questions with short answers written with the fact in view; up to 12 extra sampled wordings (temp 0.9) for the router only; 4 probe wordings never trained on; same questions asked about others (sister, brother, friend) and with the subject swapped, kept as the model answered them before; 6 "besides" questions about the subject that the fact does not answer; yes/no questions naming a wrong value; thinking-on twins; "Do you remember...?" variants.
3. Keep set: personal questions and other prompts with the model's current answers, so they must not change. Some are held back purely as checks, including "untold" questions (e.g. the user's cat's name) where inventing an answer fails the lesson.
4. Read: frozen model computes hidden states for all examples.
5. Input fit (pocket_fit.zig): about 10 neurons per fact, picked across layers a fifth to seven eighths deep (subject facts up to five eighths). Each neuron fires at a key row: the reply's first token, the subject's last token, or the token before the answer value. Adam, 500 steps, lr 0.01, squared hinge: activation at least 1 on the fact's rows, at most -0.25 elsewhere.
6. Output fit (pocket_values.zig): through the real forward/backward; batches of 8 fact answers + 8 answers that must stay; 12 to 60 Adam steps; weight decay; early stop when held-out loss stops falling (patience 3).
7. Interference: earlier neurons that fire on the new fact's rows are refitted silent there (must still reach 0.5 on their own rows); earlier facts on the same subject are fitted jointly (MEMIT-Merge style). Replay of up to 256 earlier answers.
8. Rounds: up to 6 rounds of 20 steps. Gate: held-out answers must come back token for token, probe wordings answered, near misses and keep prompts unchanged, no invented answers. Any failure: lesson removed whole, nothing written.
9. Save: widened shared-expert tensors (3712 to 3776) written into the safetensors shards + config.json; any MLX loader reads it. Snapshot before first lesson; rollback restores byte for byte. Delete zeroes a fact's neurons.

**Math per layer:** new_output = original_output + sum_j v_j * ReLU(u_j . h)^2. u_j = when to fire, v_j = what to add.

**Limits (author's own runs):** only Nemotron 3.5 Lightning 30B-A3B MLX 4-bit (18.5 GB); tested on M5 Ultra, M3 Ultra, GB10. Facts must name their subject ("When does the Quillmoor team deploy?" works; "When does the team deploy?" does not). 6-fact handbook: 3 to 6 of 6 across runs, with some answers bleeding to other roles. 21-fact handbook: about half kept, 6 of 16 answered, and answers about unstated things got worse. Decode about 16% slower with 21 facts. Updates/deletes fragile.

**Also in code:** learner.zig and learn_shape.zig contain a router-gated low-rank "block" path (16 ranks per layer per lesson, up to 128 lessons). Docs describe only the pocket; which path ships by default is not confirmed.

**Fit for our POC:** stores discrete, stable, subject-named facts (error code meanings, part compatibilities, escalation owners). Does not learn procedures or diagnostic sequencing. M4 Pro 24 GB fit for an 18.5 GB model plus in-place training is unverified and likely tight.
