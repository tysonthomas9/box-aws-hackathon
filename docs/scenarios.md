Fictional company: **Halvard Systems** (all names invented so the base model cannot already know them). Each scenario lists what lives in Box, what gets learned, the demo question, and what each column of the Ask screen should show.

| # | Scenario | Story | Learned by |
|---|---|---|---|
| 1 | Who do I ping about Falcon? | Jargon + hop search misses | TensorFold |
| 2 | Can Dana approve a $7k laptop? | Combining facts | TensorFold |
| 3 | The handbook changes | Box edit updates the model | TensorFold + sync |
| 4 | E42 on the X200 | Fact vs procedure | TensorFold vs LoRA |
| 5 | A procedure it never saw | Procedure generalization | LoRA |
| 6 | Don't make things up | Safety gate | TensorFold keep-or-undo |

## 1. "Who do I ping about Falcon?"
- **Box:** glossary.md says "Falcon is Halvard's billing migration project." org-chart.md says "Priya Raman leads the billing migration." The org chart never says "Falcon".
- **Learned:** both facts.
- **Without learning:** doesn't know Falcon; guesses or declines.
- **Search:** finds the glossary line for "Falcon" but not the org chart, so it explains Falcon without naming an owner.
- **With learning:** "Priya Raman, who leads the billing migration (Falcon)."
- **Proves:** learned jargon lets the model connect facts that keyword search doesn't link. Honest note: plain "What is Falcon?" is a lookup where search does fine; that question goes in the hidden test set too.

## 2. "Can Dana approve a $7k laptop order?"
- **Box:** org chart: "Dana Okafor is Halvard's IT procurement manager." Handbook: "Halvard procurement managers can approve purchases up to $5,000; above that, the VP of Finance, Marcus Lee, approves."
- **With learning:** "No, it's over Dana's $5,000 limit; Marcus Lee approves it."
- **Without / search:** without guesses; search often retrieves only one of the two passages.
- **Proves (or disproves):** whether facts stored in weights combine. This is a real experiment; report the result either way.

## 3. The handbook changes
- **Live step:** in Box, edit the handbook: the procurement limit goes from $5,000 to $10,000, and delete the line about Atlas (cancelled project).
- **Flow:** Sync shows 1 changed file, then Review shows the changed fact and the removed fact, then approve, then Learning shows the old fact deleted and the new one taught (about 2–3 minutes).
- **Ask again:** "Can Dana approve a $7k laptop?" now says yes. "What is Atlas?" no longer gives the old answer.
- **Restart** the model server and ask again: the new answer persists.
- **Risk:** TensorFold says updates and deletes are fragile; rehearse this one.

## 4. "E42 on the X200: order a new fan?"
- **Box:** X200 manual: "On the Halvard X200, error E42 means the cooling fan has failed." Runbook: "If an X200 shows E42 and the reported temperature is above 70°C, check the air intake for blockage before replacing the fan. If the temperature is normal, replace the fan."
- **Question:** "Customer's X200 shows E42 and reads 78°C. Should we ship a new fan?"
- **Facts model (TensorFold):** likely "E42 means the fan failed, so replace it": right fact, wrong action.
- **Procedures model (LoRA):** "Check the air intake first; 78°C suggests a blockage."
- **Cross-check:** teach the runbook text to TensorFold too, and the fact to LoRA, then show the facts-vs-procedures matrix.
- **Proves:** facts and procedures need different kinds of learning.

## 5. A procedure it never saw (hidden test set)
- **Training procedures** follow one pattern: rule out an environmental cause before replacing a part (E42 plus heat: check airflow; E31 plus humidity: dry the connector first).
- **Hidden family:** "An X400 shows E57 and the input voltage is 190V. Replace the logic board?" Expected: "Check the power supply and cable first; low voltage can cause E57." This family never appears in training.
- **Without LoRA:** replaces the board. **With LoRA:** checks the power supply first, if the pattern generalized.
- **Proves:** LoRA learned the habit, not just memorized the runbook. Only promoted if it beats the current version here.

## 6. Don't make things up
- **Questions nobody answered:** "What is the CEO's dog called?", "Who is the head of marketing?" (Halvard's docs don't say).
- **Expected with learning:** still "I don't know", the same as without.
- **Learning screen:** show a fact that TensorFold undid because it started answering the marketing question with Dana's name, with the reason shown.
- **Proves:** learning has a safety check, and the hidden test set catches side effects.

## Demo order (about 8 minutes)
1 → 2 → 4 → 5 on the Ask and Hidden test screens, then 3 live in Box, then 6 on the Learning screen.
