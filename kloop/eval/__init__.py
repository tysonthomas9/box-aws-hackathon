"""Injected evaluation, immutable reports, and a dev-only promotion decision."""

import math
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Annotated, Any

from pydantic import Field

from kloop.answer import SYSTEM_PROMPT, Answerer
from kloop.eval.datasets import DEV_HASH, EvalCase, QuestionSet, digest, encoded, load_dev
from kloop.eval.judge import JUDGE_MODEL, RUBRIC_HASH, BlindJudge
from kloop.ports import Artifacts, Storage
from kloop.schemas import Document, EvalReport, EvalResult, Schema

CAVEATS = [
    'The lexical audit means "no detected lexical collisions", not zero semantic leakage.',
    "The POC hidden set has been viewed and is exploratory.",
    "The 6-question addendum was sealed after training-data generation.",
    "Seen-rule/new-situation is not unseen-procedure learning.",
    "The same GLM-5 model checks the training data and judges answers.",
    "Historical search 49/52 includes the A03 contradiction/truncation caveat.",
    "Deterministic lexical checks can reject equivalent wording; raw reasons are retained.",
]


Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Bindings(Schema):
    corpus_sha256: Hash
    prompt_sha256: Hash = digest(SYSTEM_PROMPT.encode())
    audit_sha256: Hash
    manifest_sha256: Hash
    model_arns: dict[str, str]
    serving_version: str
    stale: bool = False
    judge_model: str = JUDGE_MODEL
    rubric_sha256: Hash = RUBRIC_HASH


class GateDecision(Schema):
    passed: bool
    reasons: list[str]
    counts: dict[str, Any] = Field(default_factory=dict)
    report_uri: str


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def deterministic_checks(case: EvalCase, answer: str) -> list[str]:
    """Veto missing literal values/prerequisites before the semantic judge runs."""
    reasons = []
    text = normalized(answer)
    kind = case.question.kind
    if not answer.strip():
        reasons.append("empty answer")
    if kind in {"fact", "two_fact"}:
        for required in case.required:
            # Values may be reordered in a sentence; the judge checks their relationships.
            value_tokens = set(normalized(required).split()) - {
                "a",
                "an",
                "the",
                "at",
                "on",
                "every",
                "of",
                "in",
                "cabinet",
            }
            if not value_tokens <= set(text.split()):
                reasons.append(f"missing required value: {required}")
        # Sources/citations do not constitute invented numeric facts.
        stripped = re.sub(r"\[\d+\]|\(Source:.*?\)", "", answer, flags=re.I)
        allowed = set(
            re.findall(
                r"\d+(?:\.\d+)?",
                " ".join(case.required) + case.question.question + case.question.expected_answer,
            )
        )
        if set(re.findall(r"\d+(?:\.\d+)?", stripped)) - allowed:
            reasons.append("invented numeric value")
    if kind == "untold" and not re.search(
        r"don.t know|do not know|unknown|not (?:provided|specified|available|known)|"
        r"no (?:information|documentation)|cannot (?:determine|confirm)|"
        r"can.t (?:determine|confirm)|lack.*(?:information|detail)|"
        r"not have.*(?:information|detail)",
        answer,
        re.I,
    ):
        reasons.append("missing explicit acknowledgement of not knowing")
    for forbidden in case.forbidden:
        if normalized(forbidden) in text:
            reasons.append(f"retired/stale value: {forbidden}")
    if kind == "procedure":
        rules = {
            "P01": ("4", r"inlet|pressure"),
            "P02": ("22", r"supply|voltage"),
            "P03": ("31", r"ambient|temperature"),
        }
        if case.procedure_id in rules:
            threshold, environment = rules[case.procedure_id]
            if not re.search(rf"\b{threshold}(?:\.0)?\b", answer):
                reasons.append("missing environmental threshold")
            if not re.search(environment, answer, re.I):
                reasons.append("missing environmental prerequisite")
        if not re.search(r"retest|re-test|rerun|re-run|test again", answer, re.I):
            reasons.append("missing retest prerequisite")
        if not re.search(r"persist|still|remain|clear|again", answer, re.I):
            reasons.append("missing fault outcome after retest")
    return reasons


def counts(report: EvalReport) -> dict:
    result = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "total": 0, "invented": 0}))
    for row in report.results:
        count = result[row.mode][row.kind]
        count["total"] += 1
        count["correct"] += row.passed
        count["invented"] += any(
            r == "judge: invented value" or r == "invented numeric value" for r in row.reasons
        )
    return {mode: dict(kinds) for mode, kinds in result.items()}


def paired_counts(report: EvalReport, left: str, right: str) -> dict:
    a = {r.question_id: r for r in report.results if r.mode == left}
    b = {r.question_id: r for r in report.results if r.mode == right}
    if a.keys() != b.keys() or not a:
        raise ValueError("Paired modes must have identical nonempty question ids")
    result = {"both_correct": 0, "left_only": 0, "right_only": 0, "both_wrong": 0}
    for id in a:
        if a[id].kind != b[id].kind:
            raise ValueError("Paired question kinds differ")
        key = (
            "both_correct"
            if a[id].passed and b[id].passed
            else "left_only"
            if a[id].passed
            else "right_only"
            if b[id].passed
            else "both_wrong"
        )
        result[key] += 1
    return result


def run_evaluation(
    dataset: QuestionSet,
    answerer: Answerer,
    judge: BlindJudge,
    *,
    report_id: str,
    model_version_id: str,
    bindings: Bindings,
    documents: Sequence[Document] = (),
) -> EvalReport:
    if not dataset.cases or len({c.question.id for c in dataset.cases}) != len(dataset.cases):
        raise ValueError("Nonempty unique question ids required")
    if any(c.question.split != dataset.split for c in dataset.cases):
        raise ValueError("Question split differs from report split")
    if bindings.judge_model != JUDGE_MODEL or bindings.rubric_sha256 != RUBRIC_HASH:
        raise ValueError("Judge identity/rubric must be pinned")
    if bindings.prompt_sha256 != digest(SYSTEM_PROMPT.encode()):
        raise ValueError("Serving prompt differs from report prompt")
    if not bindings.model_arns or set(bindings.model_arns) - {"without", "with", "search"}:
        raise ValueError("Explicit known model modes required")
    if "search" in bindings.model_arns and "without" in bindings.model_arns:
        if bindings.model_arns["search"] != bindings.model_arns["without"]:
            raise ValueError("Search and without must use the same base model")
    rows, metadata = [], []
    for mode, arn in bindings.model_arns.items():
        for case in dataset.cases:
            if mode == "search":
                answer = answerer.answer_search(case.question.question, arn, documents)
            else:
                answer = getattr(answerer, f"answer_{mode}")(case.question.question, arn)
            vetoes = deterministic_checks(case, answer.answer)
            rows.append(
                {
                    "question": case.question.question,
                    "answer": answer.answer,
                    "rubric": case.rubric,
                    "required": case.required,
                    "kind": case.question.kind,
                }
            )
            metadata.append((mode, case, vetoes))
    verdicts = judge.score(rows)
    if len(verdicts) != len(rows):
        raise ValueError("Judge result count mismatch")
    results = []
    for row, (mode, case, vetoes), verdict in zip(rows, metadata, verdicts, strict=True):
        passed = not vetoes and verdict.correct and not verdict.invented
        reasons = vetoes + ["judge: " + verdict.reason]
        if verdict.invented:
            reasons.append("judge: invented value")
        results.append(
            EvalResult(
                question_id=case.question.id,
                kind=case.question.kind,
                mode=mode,
                answer=row["answer"],
                passed=passed,
                score=float(passed),
                reasons=reasons,
            )
        )
    return EvalReport(
        id=report_id,
        model_version_id=model_version_id,
        split=dataset.split,
        question_set_sha256=dataset.sha256,
        results=results,
        scores={
            mode: sum(r.passed for r in results if r.mode == mode) / len(dataset.cases)
            for mode in bindings.model_arns
        },
    )


def promotion_gate(
    current: EvalReport, candidate: EvalReport, *, report_uri: str, minimum_gain: float = 0
) -> GateDecision:
    if not math.isfinite(minimum_gain) or not 0 <= minimum_gain <= 1:
        raise ValueError("minimum_gain must be an accuracy fraction from zero to one")
    if (
        current.split != "dev"
        or candidate.split != "dev"
        or current.question_set_sha256 != DEV_HASH
        or candidate.question_set_sha256 != DEV_HASH
    ):
        raise ValueError("Only the frozen dev set can drive promotion")
    a = {r.question_id: r for r in current.results if r.mode == "with"}
    b = {r.question_id: r for r in candidate.results if r.mode == "with"}
    if (
        not a
        or a.keys() != b.keys()
        or len(a) != len(current.results)
        or len(b) != len(candidate.results)
    ):
        raise ValueError("Gate needs identical unique candidate/current question ids in with mode")
    expected = {case.question.id: case.question.kind for case in load_dev().cases}
    if a.keys() != expected.keys():
        raise ValueError("Gate requires every frozen dev question")
    if any(a[id].kind != b[id].kind or a[id].kind != expected[id] for id in a):
        raise ValueError("Gate question kinds differ")
    reasons = []
    before, after = sum(r.passed for r in a.values()), sum(r.passed for r in b.values())
    if after <= before or (after - before) / len(a) + 1e-12 < minimum_gain:
        reasons.append("candidate does not meet the required strict overall gain")
    regressions = [
        id
        for id in a
        if a[id].kind in {"untold", "unrelated"} and a[id].passed and not b[id].passed
    ]
    if regressions:
        reasons.append("new untold/unrelated failures: " + ", ".join(sorted(regressions)))
    paired = {"both_correct": 0, "current_only": 0, "candidate_only": 0, "both_wrong": 0}
    by_kind = {}
    for id in a:
        key = (
            "both_correct"
            if a[id].passed and b[id].passed
            else "current_only"
            if a[id].passed
            else "candidate_only"
            if b[id].passed
            else "both_wrong"
        )
        paired[key] += 1
        group = by_kind.setdefault(a[id].kind, {"current": 0, "candidate": 0, "total": 0})
        group["current"] += a[id].passed
        group["candidate"] += b[id].passed
        group["total"] += 1
    return GateDecision(
        passed=not reasons,
        reasons=reasons or ["strict overall gain; no protected regressions"],
        counts={
            "current": before,
            "candidate": after,
            "total": len(a),
            "protected_regressions": len(regressions),
            "paired": paired,
            "by_kind": by_kind,
        },
        report_uri=report_uri,
    )


class ReportWriter:
    def __init__(
        self, artifacts: Artifacts, storage: Storage, copy_to_box: Callable[[str, bytes], None]
    ):
        self.artifacts, self.storage, self.copy_to_box = artifacts, storage, copy_to_box

    def save(self, report: EvalReport, bindings: Bindings, gate: GateDecision | None = None) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", report.id):
            raise ValueError("Report id must be a safe artifact name")
        prefix = "sealed/reports" if report.split == "hidden" else "reports"
        key = f"{prefix}/{report.id}.json"
        summary = {
            key: value for key, value in report.model_dump(mode="json").items() if key != "results"
        }
        summary.update(
            counts=counts(report),
            bindings=bindings.model_dump(mode="json"),
            caveats=CAVEATS,
            gate=gate.model_dump(mode="json") if gate else None,
        )
        modes = list(bindings.model_arns)
        summary["paired"] = {
            f"{a}_vs_{b}": paired_counts(report, a, b)
            for i, a in enumerate(modes)
            for b in modes[i + 1 :]
        }
        # Raw hidden answers stay evaluator-private; Box/UI receive aggregate counts only.
        data = encoded({**summary, "results": [r.model_dump(mode="json") for r in report.results]})
        try:
            existing = self.artifacts.get(key)
        except KeyError:
            self.artifacts.put(key, data, "application/json")
        else:
            if existing != data:
                raise ValueError("Report id already contains different immutable evidence")
        self.copy_to_box(f"{report.id}.json", encoded(summary))
        self.storage.put("eval_reports", report.id, summary)
        return key


class Evaluator:
    """Pipeline adapter; caller owns serving-version CAS and every resource lifecycle."""

    def __init__(
        self,
        answerer: Answerer,
        judge: BlindJudge,
        writer: ReportWriter,
        *,
        current_arn: Callable[[str], str],
        audit_hash: Callable[[str, str], str],
        dataset: QuestionSet | None = None,
        minimum_gain: float = 0,
    ):
        self.answerer, self.judge, self.writer = answerer, judge, writer
        self.current_arn, self.audit_hash = current_arn, audit_hash
        self.dataset = dataset
        if not math.isfinite(minimum_gain) or not 0 <= minimum_gain <= 1:
            raise ValueError("minimum_gain must be an accuracy fraction from zero to one")
        self.minimum_gain = minimum_gain

    def evaluate(
        self,
        candidate_arn: str,
        snapshot_hash: str,
        manifest_hash: str,
        expected_current_version: str,
        dev_set_hash: str,
    ) -> GateDecision:
        if dev_set_hash != DEV_HASH:
            raise ValueError("Frozen dev hash required")
        dataset = self.dataset or load_dev()
        if dataset.split != "dev" or dataset.sha256 != DEV_HASH:
            raise ValueError("Evaluator requires frozen dev set")
        audit = self.audit_hash(
            manifest_hash, snapshot_hash
        )  # Must validate passed, hash-bound audit upstream.
        if not re.fullmatch(r"[a-f0-9]{64}", audit):
            raise ValueError("A verified overlap audit hash is required")
        bindings = Bindings(
            corpus_sha256=snapshot_hash,
            audit_sha256=audit,
            manifest_sha256=manifest_hash,
            model_arns={
                "without": self.current_arn(expected_current_version),
                "with": candidate_arn,
            },
            serving_version=expected_current_version or "base",
        )
        combined = run_evaluation(
            dataset,
            self.answerer,
            self.judge,
            report_id="eval-" + digest(encoded(bindings.model_dump(mode="json"))),
            model_version_id=manifest_hash,
            bindings=bindings,
        )
        reports, bindings_list = [], []
        for label, mode in (("current", "without"), ("candidate", "with")):
            reports.append(
                combined.model_copy(
                    update={
                        "id": combined.id + "-" + label,
                        "model_version_id": (expected_current_version or "base")
                        if label == "current"
                        else manifest_hash,
                        "results": [
                            r.model_copy(update={"mode": "with"})
                            for r in combined.results
                            if r.mode == mode
                        ],
                        "scores": {"with": combined.scores[mode]},
                    }
                )
            )
            bindings_list.append(
                bindings.model_copy(
                    update={
                        "model_arns": {"with": bindings.model_arns[mode]},
                    }
                )
            )
        uri = f"reports/{reports[1].id}.json"
        decision = promotion_gate(*reports, report_uri=uri, minimum_gain=self.minimum_gain)
        for report, bindings in zip(reports, bindings_list, strict=True):
            self.writer.save(report, bindings, decision)
        return decision
