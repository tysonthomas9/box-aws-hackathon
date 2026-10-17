# Evaluation and promotion gate

> Workspace snapshot: 2026-10-17 07:45 UTC. Source note: `31cfbb2b-f39f-43b3-8ea5-0823605c0ed7`. Task status: **complete**. Earlier progress entries are historical; later dated entries record updates.

Score versions and decide promotion.

## Scope
`kloop/eval/`: run question sets through the answering library in each mode; code checks (expected value present, "I don't know" for untold questions, no invented values) plus a GLM-5 judge with a rubric (as in POC 2). The **dev set** drives the gate: promote only if the candidate beats the current version overall and has no new failures on unrelated/untold questions. The **sealed hidden set** is run only for reporting; verify its hash before running, and never expose it to the data builder (separate S3 prefix and IAM). Reports by question type with raw counts, saved to S3 and copied to Box `reports/`.
Not in scope: Bedrock Evaluations jobs.

## Definition of Done
Tests with fake answers; reproduces POC 2's baseline numbers within judge noise on the same model; the gate decision is logged with its reasons.

## Verification
`make test`; `make eval-live MODE=without`.

## Shared rules
Read the [Spec](../spec.md) Decisions first. Region us-east-2, profile box-hackathon. Python 3.12 + uv. No secrets in code, logs or state. Standing rules: no AWS Support cases or quota requests; stop before any single action > $10; no rm outside /tmp; no Claude attribution in commits.

## Changes from the phase 1 plan review (2026-10-17). These override the text above.
- **Isolation:** the hidden-set overlap audit runs here, in a separate evaluator role, after the training data is immutable. It returns a hash-bound verdict and never returns hidden content. The data builder's role cannot read the hidden prefix.
- **Blind judging:** strip and shuffle mode labels before GLM-5 sees answers; pin the judge model and rubric; deterministic value/prerequisite checks run first and can fail an answer the judge passed.
- **Reports:** all three modes (without / with / search), each bound to the same corpus, question-set, prompt and model versions plus the audit hash. Report paired raw counts, not just percentages.
- **Honest caveats in every report:** the lexical audit means "no detected lexical collisions", not zero semantic leakage; the POC hidden set has been viewed (exploratory); the 6-question addendum was sealed after training-data generation; seen-rule/new-situation is not unseen-procedure learning; the same model checks the data and judges answers.
- **Update/retirement probes:** version-specific questions show whether the changed value and the retired item are reflected; show the serving version and stale status.
- DoD adds: reproduce POC 2's base and search numbers on the same model (keep the historical 49/52 with its A03/truncation caveat) and run all three modes live.


## Dev set (frozen 2026-10-17)
The dev set is `poc/model-experiment/data/dev.jsonl` (30 questions, 8 untold), SHA256 `5773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf`, commit 02d0857, audited against the hidden set, the addendum, the 386 training rows and itself. Reference it by path and hash; don't copy or edit it.

Implementation started. Scope: kloop/eval/, tests/test_eval.py, evaluation command include. Frozen dev set and sealed hash verification; blinded GLM-5 prompt based on POC 2; deterministic vetoes; public summaries in Storage eval_reports and private reports artifact. Pipeline owns promotion CAS and cleanup; evaluator returns passed/counts/report_uri. Live restricted to base 0inmdc8ttj1w without/search per coordinator.

Core implemented with 14 focused credential-free tests: sealed/dev readers; hash-bound lexical audit; shuffled opaque GLM-5 judging; deterministic vetoes; full-dev strict gain/protected-regression gate and minimum gain; private raw artifacts plus public S3/Box/UI summaries; evaluator-only runtime factory/handler. Training owns separate Lambda/IAM wiring. Normal full suite passed 219; credential-free full suite passed 219. Shared lint initially blocked by training files (owner notified), now only web/jobs formatting (owner notified). Live all-mode DEV proof running with POC2 retained 4B weights; original attempt interrupted by harness restart after 25 answers and resumed from cache. No cloud resource creation/deletion.

## Completion and measured proof — 2026-10-17

Completed and pushed on withered-cobra.

Commits: e25a059d5d44af397cd3e6f50d41a30836580f3d (implementation + proof), 7e68a5b4232aa773b490321f4df7d7c9a1389287 (verified public overlap status + final gates). Main implementation parent d1fb36b1390ed28f778d3df8ac533ca272344901; final follow-up parent bdd954775977658627af12b8a343299288ae92d2. Final tree 52a359dca4ce9f729a4add432e0c629cee7eef73. Training owner added the eval Makefile include in bdd9547. No PR exists (gh pr list --head withered-cobra returned []); no PR created.

Delivered:
- Frozen dev reader uses original path/hash without copying or editing it; sealed 46+6 hashes checked before use.
- POC 2 GLM-5 rubric pinned by hash, opaque shuffled ids, no model/mode/version metadata sent to judge. Strict complete verdict coverage/type checks; one JSON fence accepted.
- Deterministic required values, invented numeric values, explicit unknowns and environmental/retest prerequisites veto judge passes. Generic value-token checks allow sentence reordering.
- Dev-only full-set gate requires strict overall gain, configured minimum accuracy gain and zero new untold/unrelated failures. Hidden reports cannot select or promote. Decision includes reasons, raw paired counts and counts by kind.
- Evaluator-only immutable-training overlap audit emits hash-bound lexical verdicts; builder never receives hidden content. Runtime handler matches training's exact candidate/snapshot/manifest/current/dev kwargs; pipeline owns promotion CAS and cleanup.
- Private raw hidden artifacts use sealed/reports/. Public summaries contain counts/bindings/caveats; Box gets aggregate summaries only. Report retries refuse different immutable evidence. Results overlap_audit is exposed only after rehashing the real stored verdict, not inferred from an audit hash.
- Version-specific change/retirement probes have their own sealed reader/hash and separate reporting sets; serving version and stale are explicit bindings.
- make eval-live supports without/with/search/all/baseline. Trained live runs are limited to dev; hidden with is refused by this proof command.

Measured live proof, imported Qwen3-4B 32K, us-east-2, profile box-hackathon:
- Base 0inmdc8ttj1w; retained trained POC 2 import ol1fd5dnxm6w. These are POC 2 weights, not model-experiment-v2 training.
- Dev (30): without 12, with 17, search 28. Untold: 7/8, 0/8, 8/8. Diagnostic gate REJECTED: seven newly failing protected questions despite overall gain; no serving pointer was changed.
- Sealed hidden 52: without 22/52 (POC 2 baseline 22/52), search 50/52 (historical 49/52). Search by kind: fact20/20, two_fact5/5, procedure6/7, untold10/10, unrelated9/10. Paired without vs search: both correct21, without only1, search only29, both wrong1.
- New blind judge-only counts are base27/search50; deterministic checks veto five unsupported base credits. The one-answer search difference is reported as judge/retrieval variation, not a learning result.
- Preserve historical 49/52 A03/truncation caveat. Current search A03 also adds an unsupported extra prerequisite that GLM-5 passes; counts are model-judged/exploratory, not human-adjudicated truth. Original hidden set was viewed; addendum sealed after data generation; lexical audit is not zero semantic leakage; seen-rule/new-situation is not unseen-procedure learning; same GLM-5 checks training and judges.
- Harness restart interrupted first answer attempt after25 cached responses; all later retries reuse cached native generations/verdicts. Parser/matcher corrections used cache-only replay with zero new inference calls.
- Conservative cumulative spend upper bound $3.4940878 within $5 reservation, including interrupted attempt and double-counted idle windows; final bill may differ. No cloud resources created/deleted; no Support/quota requests. AWS plan verified FREE. No cleanup choice needed because nothing was created.

Verification 2026-10-17 ~07:36 UTC: normal make test && make lint PASS280; fully credential-free same command PASS280; focused tests/test_eval.py PASS18; git diff --check PASS; make eval-live MODE=baseline PASS using cached proof; make -n eval-live MODE=without resolves correctly. Source hashes and credential-free log retained in poc/evaluation/evidence/verification.json and credential-free-gates.log. Only warning is Starlette/httpx deprecation. No known failing base CI result or CI failure link is claimed.

Files: kloop/eval/{__init__,datasets,judge,live,runtime}.py and commands.mk; tests/test_eval.py; poc/evaluation/evidence/** (raw caches, judge outputs, comparison.json, reports, spend-summary.json, verification.json/log). No shared schema, answerer, Makefile, Terraform or peer changes staged by evaluation. Published from owned detached temporary worktree after pull --rebase; removed that worktree; left peer experiment evidence untouched.

Deployment-wave verification still required: assume evaluator IAM role, upload sealed inputs to its private S3 prefix, execute evaluation Lambda, verify S3 writes and CCG Box reports publication with real services, and run version probes against deployed serving versions. Those are not claimed by fake adapter tests or local inference proof.

## Verifier findings — evaluation task, 2026-10-17

### Verification Summary
- Verdict: ✅ APPROVED (PASS for task 31cfbb2b-f39f-43b3-8ea5-0823605c0ed7).
- Confidence: High for the assigned code, fake-adapter contracts, and offline replay of committed live inference evidence.
- Reviewed/tested head: 7e68a5b4232aa773b490321f4df7d7c9a1389287; tree 52a359dca4ce9f729a4add432e0c629cee7eef73. Local HEAD, origin/withered-cobra and git ls-remote origin refs/heads/withered-cobra agree.
- Scope is this evaluation task's Definition of Done and review overrides. Bedrock Evaluations jobs are explicitly excluded. Deployment-wave real IAM/S3/Box verification is separate; this is not full-stack runtime acceptance.
- No failing criteria or spec ambiguity. No product code changes, service clients, live AWS/Box calls, cloud resources or spend from verification.

### Acceptance Criteria Checklist
- ✅ VERIFIED — Tests with fake answers; deterministic checks plus pinned, blinded GLM-5.
  - Evidence: kloop/eval/__init__.py:54,152; judge.py:11,43; tests/test_eval.py:98,133,139,234,261,369. Opaque shuffled IDs, explicit allowlist, pinned model/rubric, strict complete verdict coverage; value/prerequisite checks veto judge passes.
  - Verification: 18 focused tests and full 280-test suite pass. Offline cached judge requests match the shipped rubric/request hashes.
- ✅ VERIFIED — Frozen dev set drives strict improvement with no new untold/unrelated failures; log decision and reasons.
  - Evidence: datasets.py:51; __init__.py:226,378; committed dev-all/report.json diagnostic_gate. Gate requires all 30 frozen questions with matching kinds/hash, rejects hidden/partial sets, applies minimum gain.
  - Verification: gate regression tests pass; independent offline replay reproduced 12/30 current versus 17/30 candidate and REJECTED for seven protected regressions, including exact reasons and paired counts.
- ✅ VERIFIED — Hidden hash verification and isolated, hash-bound overlap audit after immutable training.
  - Evidence: datasets.py:44,82,110; runtime.py:22; infra/training.tf:94,153-169. Evaluator rehashes manifest/train/sealed inputs; audit returns hashes/count/verdict without hidden content; worker has training-prefix access and no evaluator-role assumption.
  - Verification: tampered input/manifest/training tests pass; static IAM review. No claim of deployed role assumption.
- ✅ VERIFIED — All-mode reports with common corpus/question/prompt/model/audit bindings, per-kind and paired raw counts, S3/Box writer.
  - Evidence: __init__.py:31,118,130,295; runtime.py:52; tests/test_eval.py:211,224,234,357,382. Raw hidden results use sealed/reports; Box/UI summaries exclude answers; public audit status rehashes the stored verdict; differing immutable retries fail.
  - Verification: fake storage/artifact/Box contracts pass. Offline all-mode dev replay reproduced without/with/search 12/17/28 and every paired/per-kind count; hidden base/search 22/50 reproduced. Publication was verified with fakes, as stated in the task handoff.
- ✅ VERIFIED — Required honesty caveats in every report and historical 49/52 A03/truncation caveat.
  - Evidence: __init__.py:16 CAVEATS; ReportWriter.save; live.py report summary; evidence/comparison.json limits. Includes exploratory hidden set, post-generation addendum sealing, lexical-only audit, seen-rule caveat and same checking/judging model.
  - Verification: source and committed reports inspected; reports contain the caveats. Search A03 over-credit is expressly disclosed in comparison.json, not represented as human-adjudicated correctness.
- ✅ VERIFIED — Version-specific update/retirement probes with serving-version and stale fields.
  - Evidence: datasets.py:140 sealed per-version reader; __init__.py:31 Bindings; tests/test_eval.py:289.
  - Verification: focused tests load distinct v1/v2 sets, reject old value and retired Q-14 guidance; static report bindings verified. Running these against deployed serving versions belongs to deployment verification.
- ✅ VERIFIED — Reproduce POC 2 base/search on same model within judge noise and run all three modes live.
  - Evidence: committed dev-all and hidden-baseline native-generation/judge caches, reports and comparison.json; same base imported-model/0inmdc8ttj1w, retained POC2 trained import ol1fd5dnxm6w.
  - Verification: no-network replay constructed no AWS clients and reproduced all 194 result rows from request-hash-keyed cached generations and exact blinded verdict requests. Baseline 22/52 matches historical 22/52; search 50/52 versus historical 49/52 is the disclosed one-answer variation. All three modes have dev live evidence; hidden-with was not authorized and is not claimed.
- ✅ VERIFIED — Credential-free make test and lint.
  - Evidence: independent current-head run with AWS profiles/keys/session unset and AWS config/credentials=/dev/null; 280 tests pass, ruff check and all 75 format checks pass.
  - Verification: exact commands below. Only warning: Starlette/httpx deprecation.

### Evidence index
- Commits reviewed: e25a059d5d44af397cd3e6f50d41a30836580f3d, 7e68a5b4232aa773b490321f4df7d7c9a1389287, command integration bdd954775977658627af12b8a343299288ae92d2.
- Implementation base from task context: d1fb36b1390ed28f778d3df8ac533ca272344901.
- Notes: task 31cfbb2b-f39f-43b3-8ea5-0823605c0ed7; PR context 846fb942-136d-4b81-98f2-354a4926f1de (evaluation handoff); Spec Goal/Decisions/Non-goals/Acceptance Criteria/Verification Plan.
- Files: all kloop/eval sources; tests/test_eval.py; evaluation evidence verification/comparison/reports and request-keyed caches; Makefile; answerer; training IAM and package inclusion.
- All seven evaluation source hashes match verification.json and git show reviewed-head:path.
- Report SHA256: dev-all a1bfb4f78dee8039804fd0e25f327b55fa671461af40cf6641ec21dd65338097; hidden-baseline 1cebfed49dc7e163461aa165d976fb666201aee6c823d787714eca1aae97f667.

### Tests/Commands Run
- Credential-free make test && make lint → PASS (280 tests, lint and format).
- uv run --locked pytest tests/test_eval.py -q → PASS (18 tests).
- git diff --check d1fb36b1390ed28f778d3df8ac533ca272344901 7e68a5b4232aa773b490321f4df7d7c9a1389287 → PASS.
- make -n eval-live MODE=without → PASS (resolves hidden without target; no inference).
- Offline cached replay → PASS: every result, score, per-kind count, pair and diagnostic decision matches committed report.
- Initial custom replay attempted sorted JSON model order, resulting in a missing cache key; corrected to the live command's original without/with/search order. No inference fallback exists in replay, so no service call occurred.
- make eval-live MODE=without intentionally not executed: it can make paid inference calls. Prior live proof was independently replayed offline instead.
- git status --short unchanged from entry: peer train4.json/train8.json evidence modified, AGENTS.md/CLAUDE.md untracked; verifier did not edit these.

### Exact re-verify commands
```sh
git rev-parse HEAD
git ls-remote origin refs/heads/withered-cobra
env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true make test
env -u AWS_PROFILE -u AWS_DEFAULT_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true make lint
uv run --locked pytest tests/test_eval.py -q
git diff --check d1fb36b1390ed28f778d3df8ac533ca272344901 7e68a5b4232aa773b490321f4df7d7c9a1389287
make -n eval-live MODE=without
```

Offline cache replay (read-only; a missing cache raises, never invokes a model):
```sh
uv run --locked python - <<'PY'
import json
from pathlib import Path
from kloop.answer import Answerer
from kloop.eval import Bindings, counts, paired_counts, promotion_gate, run_evaluation
from kloop.eval.datasets import digest, encoded, load_dev, load_hidden
from kloop.eval.judge import BlindJudge
from kloop.schemas import Document
root = Path("poc/evaluation/evidence")
raw = Path("pack/pack.json").read_bytes()
pack = json.loads(raw)
docs = [Document(file_id=r["id"], version_id=digest(raw), name=r["source"],
    text=r.get("text", r.get("rule"))) for r in pack["facts"] + pack["procedures"]]
class Model:
    def __init__(self, p): self.p = p
    def invoke(self, model_id, payload):
        return json.loads((self.p / (digest(encoded([model_id, payload])) + ".json")).read_bytes())
class Judge:
    def __init__(self, p): self.p = p
    def converse(self, **kw):
        return json.loads((self.p / ("judge-" + digest(encoded(kw)) + ".json")).read_bytes())
comp = json.loads((root / "comparison.json").read_bytes())
for name, data, modes in [("dev-all", load_dev(), ["without", "with", "search"]),
                          ("hidden-baseline", load_hidden(), ["without", "search"])]:
    p = root / name
    raw = (p / "report.json").read_bytes()
    assert digest(raw) == comp["report_hashes"][name]
    s = json.loads(raw)
    b = Bindings.model_validate({**s["bindings"],
        "model_arns": {m: s["bindings"]["model_arns"][m] for m in modes}})
    r = run_evaluation(data, Answerer(Model(p)), BlindJudge(Judge(p)),
        report_id=s["id"], model_version_id=s["model_version_id"], bindings=b, documents=docs)
    assert all(v == s[k] for k, v in r.model_dump(mode="json").items())
    assert counts(r) == s["counts"]
    assert {f"{a}_vs_{b}": paired_counts(r, a, b)
        for i, a in enumerate(modes) for b in modes[i+1:]} == s["paired"]
    if name == "dev-all":
        reports = [r.model_copy(update={"results": [
            x.model_copy(update={"mode": "with"}) for x in r.results if x.mode == m]})
            for m in ["without", "with"]]
        assert promotion_gate(*reports, report_uri=s["diagnostic_gate"]["report_uri"],
            minimum_gain=.05).model_dump(mode="json") == s["diagnostic_gate"]
    print(name, "PASS")
PY
```

### Risk Notes
- Model-judged exploratory evidence does not establish human-adjudicated correctness or zero semantic leakage.
- No new live inference, deployed evaluator role assumption, S3 publication or CCG Box publication was attempted. Full deployment and served update/retirement probes remain deployment-wave checks, already disclosed by the implementor.
