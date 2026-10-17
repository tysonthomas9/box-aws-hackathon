"""Injected evaluation, immutable reports, and a dev-only promotion decision."""

import math
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field

from kloop.answer import SYSTEM_PROMPT, Answerer
from kloop.eval.datasets import EvalCase, QuestionSet, digest, encoded, load_dev_for_hash
from kloop.eval.frozen import FROZEN_RUBRIC_HASH, FROZEN_SET_HASHES
from kloop.eval.frozen import deterministic_checks as frozen_checks
from kloop.eval.judge import CRITERIA_RUBRIC_HASH, JUDGE_MODEL, RUBRIC_HASH, BlindJudge
from kloop.ports import Artifacts, Storage
from kloop.schemas import CriterionResult, Document, EvalReport, EvalResult, Schema

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
    rubric_scoring: bool | None = None
    criteria_rubric_sha256: Hash = CRITERIA_RUBRIC_HASH

    def criteria_enabled(self, dataset: QuestionSet) -> bool:
        if self.rubric_scoring is not None:
            return self.rubric_scoring
        return dataset.sha256 not in FROZEN_SET_HASHES and any(c.criteria for c in dataset.cases)


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
    if kind in {"fact", "two_fact", "procedure", "rule_in_question"}:
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
    return reasons


def counts(report: EvalReport) -> dict:
    result = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "total": 0, "invented": 0}))
    for row in report.results:
        count = result[row.mode][row.kind]
        count["total"] += 1
        count["correct"] += row.passed
        count["invented"] += (
            any(r == "judge: invented value" or r == "invented numeric value" for r in row.reasons)
            or row.invented
        )
    return {mode: dict(kinds) for mode, kinds in result.items()}


def diagnostic_counts(report: EvalReport) -> dict:
    """Additional report rows; none of these values drive promotion."""
    result = {}
    by_mode = counts(report)
    for mode in dict.fromkeys(r.mode for r in report.results):
        rows = [r for r in report.results if r.mode == mode]
        criteria = [c for r in rows for c in r.criteria]
        withheld = [r for r in rows if r.bucket == "in_documents_not_trained"]
        passed = sum(c.passed for c in criteria)
        result[mode] = {
            "criteria": {
                "passed": passed,
                "total": len(criteria),
                "pass_rate": passed / len(criteria) if criteria else None,
            },
            "in_documents_not_trained": {
                "correct": sum(r.passed for r in withheld),
                "declined": sum(r.declined and not r.passed and not r.invented for r in withheld),
                "invented": sum(r.invented for r in withheld),
                "total": len(withheld),
            },
            "invented_answers": {
                "total": sum(v["invented"] for v in by_mode[mode].values()),
                "answers": len(rows),
                "on_untold": by_mode[mode].get("untold", {}).get("invented", 0),
            },
        }
    return result


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
    approved_quotes: Mapping[tuple[str, str], Sequence[str]] | None = None,
) -> EvalReport:
    if not dataset.cases or len({c.question.id for c in dataset.cases}) != len(dataset.cases):
        raise ValueError("Nonempty unique question ids required")
    if any(c.question.split != dataset.split for c in dataset.cases):
        raise ValueError("Question split differs from report split")
    rubrics = {RUBRIC_HASH}
    if dataset.sha256 in FROZEN_SET_HASHES:
        rubrics.add(FROZEN_RUBRIC_HASH)
    if bindings.judge_model != JUDGE_MODEL or bindings.rubric_sha256 not in rubrics:
        raise ValueError("Judge identity/rubric must be pinned")
    if isinstance(judge, BlindJudge) and digest(judge.rubric.encode()) != bindings.rubric_sha256:
        raise ValueError("Judge prompt differs from report rubric")
    rubric_scoring = bindings.criteria_enabled(dataset)
    if rubric_scoring and bindings.criteria_rubric_sha256 != CRITERIA_RUBRIC_HASH:
        raise ValueError("Criterion judge rubric must be pinned")
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
                options = (
                    {"approved_quotes": approved_quotes} if approved_quotes is not None else {}
                )
                answer = answerer.answer_search(case.question.question, arn, documents, **options)
            else:
                answer = getattr(answerer, f"answer_{mode}")(case.question.question, arn)
            check = frozen_checks if dataset.sha256 in FROZEN_SET_HASHES else deterministic_checks
            vetoes = check(case, answer.answer)
            rows.append(
                {
                    "question": case.question.question,
                    "expected_answer": case.question.expected_answer,
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
    criterion_rows, criterion_owners = [], []
    if rubric_scoring:
        for index, (row, (_, case, _)) in enumerate(zip(rows, metadata, strict=True)):
            if verdicts[index].declined and not verdicts[index].invented:
                continue
            for criterion in case.criteria:
                criterion_rows.append(
                    {
                        **row,
                        "rubric": encoded(
                            {
                                "criterion": criterion.text,
                                "source_quote": criterion.supporting_quote,
                            }
                        ).decode(),
                        "required": [],
                    }
                )
                criterion_owners.append((index, criterion.id))
    criterion_results = defaultdict(list)
    if criterion_rows:
        scored = judge.score_criteria(criterion_rows)
        if len(scored) != len(criterion_rows):
            raise ValueError("Criterion judge result count mismatch")
        for (index, id), verdict in zip(criterion_owners, scored, strict=True):
            criterion_results[index].append(
                CriterionResult(
                    id=id, passed=verdict.correct and not verdict.invented, reason=verdict.reason
                )
            )
    results = []
    for row, (mode, case, vetoes), verdict in zip(rows, metadata, verdicts, strict=True):
        invented = verdict.invented or "invented numeric value" in vetoes
        declined = verdict.declined and not invented
        passed = (
            not vetoes
            and verdict.correct
            and not invented
            and (not declined or case.question.kind == "untold")
        )
        if case.bucket == "in_documents_not_trained" and not passed and not declined:
            invented = True
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
                bucket=case.bucket,
                invented=invented,
                declined=declined,
                criteria=criterion_results[len(results)],
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
        or current.question_set_sha256 != candidate.question_set_sha256
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
    dataset = load_dev_for_hash(current.question_set_sha256)
    expected = {case.question.id: case.question.kind for case in dataset.cases}
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
        self,
        artifacts: Artifacts,
        storage: Storage,
        copy_to_box: Callable[[str, bytes], None],
        *,
        audit_lookup: Callable[[str], dict] | None = None,
    ):
        self.artifacts, self.storage, self.copy_to_box = artifacts, storage, copy_to_box
        self.audit_lookup = audit_lookup

    def save(self, report: EvalReport, bindings: Bindings, gate: GateDecision | None = None) -> str:
        from kloop.eval.medical import DEV_HASH as MEDICAL_DEV_HASH
        from kloop.eval.medical import HIDDEN_HASH as MEDICAL_HIDDEN_HASH
        from kloop.eval.medical import category_counts

        medical = report.question_set_sha256 in {MEDICAL_DEV_HASH, MEDICAL_HIDDEN_HASH}
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", report.id):
            raise ValueError("Report id must be a safe artifact name")
        prefix = "sealed/reports" if report.split == "hidden" else "reports"
        key = f"{prefix}/{report.id}.json"
        summary = {
            key: value for key, value in report.model_dump(mode="json").items() if key != "results"
        }
        summary.update(
            counts=counts(report),
            diagnostics=diagnostic_counts(report),
            bindings=bindings.model_dump(mode="json"),
            caveats=CAVEATS,
            gate=gate.model_dump(mode="json") if gate else None,
        )
        if medical:
            summary["medical_counts"] = category_counts(report)
            summary["caveats"] = [
                CAVEATS[0],
                CAVEATS[4],
                CAVEATS[6],
                "Synthetic medical corpus; expected answers describe approved source documents.",
                "Untrained-document facts use the same source answer in all modes; declines "
                "and invented values are reported separately.",
                "Supplied-rule cases test application of rules stated in the question.",
            ]
        if self.audit_lookup is not None:
            audit = self.audit_lookup(bindings.audit_sha256)
            verdict = {k: v for k, v in audit.items() if k != "sha256"}
            if (
                digest(encoded(verdict)) != bindings.audit_sha256
                or audit["sha256"] != bindings.audit_sha256
                or type(audit["passed"]) is not bool
            ):
                raise ValueError("Public overlap verdict does not match its audit hash")
            summary["overlap_audit"] = {
                "passed": audit["passed"],
                "sha256": audit["sha256"],
                "scope": (
                    "immutable training versus sealed medical dev+hidden; lexical only"
                    if medical
                    else "immutable training versus sealed 46+6; lexical collisions only"
                ),
                "training_sha256": audit["training_sha256"],
                "question_set_sha256": audit["question_set_sha256"],
            }
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
        rubric_scoring: bool | None = None,
    ):
        self.answerer, self.judge, self.writer = answerer, judge, writer
        self.current_arn, self.audit_hash = current_arn, audit_hash
        self.dataset = dataset
        if not math.isfinite(minimum_gain) or not 0 <= minimum_gain <= 1:
            raise ValueError("minimum_gain must be an accuracy fraction from zero to one")
        self.minimum_gain = minimum_gain
        self.rubric_scoring = rubric_scoring

    def evaluate(
        self,
        candidate_arn: str,
        snapshot_hash: str,
        manifest_hash: str,
        expected_current_version: str,
        dev_set_hash: str,
    ) -> GateDecision:
        sealed = load_dev_for_hash(dev_set_hash)
        dataset = self.dataset or sealed
        if dataset != sealed:
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
            rubric_scoring=self.rubric_scoring,
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
