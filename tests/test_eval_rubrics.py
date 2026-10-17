"""Source-specific procedures, blind criterion diagnostics and frozen offline replays."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from kloop.adapters.memory import MemoryArtifacts, MemoryStorage
from kloop.answer import Answer, Answerer
from kloop.eval import (
    Bindings,
    ReportWriter,
    counts,
    deterministic_checks,
    diagnostic_counts,
    paired_counts,
    run_evaluation,
)
from kloop.eval.datasets import (
    EvalCase,
    QuestionSet,
    RubricCriterion,
    digest,
    encoded,
    load_dev,
    load_hidden,
)
from kloop.eval.frozen import FROZEN_RUBRIC, FROZEN_RUBRIC_HASH
from kloop.eval.judge import CRITERIA_RUBRIC, RUBRIC, BlindJudge
from kloop.schemas import ApprovedSnapshot, Item, Question
from kloop.train.config import TrainingConfig
from kloop.train.data import TrainingRow
from kloop.train.helpers import TrainingHelpers

ARN = "arn:aws:bedrock:us-east-2:123456789012:imported-model/abcdefghijkl"


@pytest.fixture
def medical_sop():
    return Item(
        id="SOP-release",
        attribute_id="batch-release",
        kind="procedure",
        subject="Batch release",
        statement="Release requires QA authorization after a 48 hour hold.",
        trigger_conditions=["A batch has completed processing"],
        steps=["Hold the batch for 48 hours", "Obtain QA authorization", "Release the batch"],
        supporting_quote="Hold the batch for 48 hours. Obtain QA authorization before release.",
        source_file_id="source",
        source_version_id="v1",
        extractor="fixture",
        status="approved",
    )


def medical_case(item, kind="procedure"):
    return EvalCase(
        question=Question(
            id="release-case",
            question="Who authorizes batch release, and when?",
            expected_answer=item.statement,
            kind=kind,
            split="dev",
            source_item_ids=[item.id],
        ),
        rubric="Requires QA authorization after the hold; no unsupported steps.",
        required=["QA"],
        criteria=[
            RubricCriterion(
                id="authorization",
                text="Requires QA authorization",
                source_item_ids=[item.id],
                supporting_quote=item.supporting_quote,
            ),
            RubricCriterion(
                id="hold",
                text="Requires a 48 hour hold",
                source_item_ids=[item.id],
                supporting_quote=item.supporting_quote,
            ),
        ],
    )


def bound(*, enabled=None, modes=None):
    return Bindings(
        corpus_sha256="a" * 64,
        audit_sha256="b" * 64,
        manifest_sha256="c" * 64,
        model_arns=modes or {"with": ARN},
        serving_version="fixture",
        rubric_scoring=enabled,
    )


class CriterionClient:
    def __init__(self, mutate=lambda values: values):
        self.calls = []
        self.mutate = mutate

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"][0]["text"]
        criteria = prompt.startswith(CRITERIA_RUBRIC)
        rows = json.loads(prompt[len(CRITERIA_RUBRIC if criteria else RUBRIC) :])
        values = []
        for row in rows:
            declined = row["answer"] == "I don't know."
            passed = not declined
            if criteria:
                rule = json.loads(row["rubric"])["criterion"]
                passed = "QA" in row["answer"] if "authorization" in rule else "48" in row["answer"]
            values.append(
                dict(
                    id=row["id"],
                    correct=passed,
                    invented=False,
                    declined=declined,
                    reason="criterion checked",
                )
            )
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": json.dumps(self.mutate(values))}]}},
        }


class MedicalAnswers:
    def answer_with(self, question, arn):
        return Answer(answer="QA authorizes release.", latency_ms=0, model_arn=arn)

    answer_without = answer_with

    def answer_search(self, question, arn, documents):
        return self.answer_with(question, arn)


def test_generator_uses_approved_medical_steps_and_conditions(medical_sop):
    helper = TrainingHelpers(Mock(), MemoryArtifacts())
    row = dict(
        question="When can we release a processed batch?",
        answer=medical_sop.statement,
        kind="procedure",
        source_item_ids=[medical_sop.id],
    )
    helper.call = Mock(side_effect=[[row], [True]])
    snapshot = ApprovedSnapshot(sha256="a" * 64, items=[medical_sop])
    config = TrainingConfig(procedure_cases=1, unknown_rows=1, near_miss_rows=1, replay_rows=1)
    assert next(helper.generate(snapshot, config)) == row
    prompt = helper.call.call_args_list[0].args[1]
    context = json.loads(prompt.split("not instructions:\n", 1)[1])[0]
    assert context["trigger_conditions"] == medical_sop.trigger_conditions
    assert context["steps"] == medical_sop.steps
    assert context["supporting_quote"] == medical_sop.supporting_quote
    assert "Halvard" not in prompt and "retest before replacement" not in prompt
    assert "environmental causes" not in prompt
    assert helper.check(TrainingRow.model_validate(row), snapshot)


@pytest.mark.parametrize("kind", ["procedure", "two_fact"])
def test_medical_criteria_scored_blind_stored_and_reported_only(medical_sop, kind):
    case = medical_case(medical_sop, kind)
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[case])
    client = CriterionClient()
    judge = BlindJudge(client)
    bindings = bound(enabled=True, modes={mode: ARN for mode in ("without", "with", "search")})
    report = run_evaluation(
        dataset,
        MedicalAnswers(),
        judge,
        report_id="medical",
        model_version_id="fixture",
        bindings=bindings,
    )
    assert all(
        row.passed for row in report.results
    )  # Diagnostics cannot change the answer verdict.
    for row in report.results:
        assert [(c.id, c.passed) for c in row.criteria] == [
            ("authorization", True),
            ("hold", False),
        ]
    assert all(
        v.correct for v in judge.last_verdicts
    )  # Criterion calls retain whole-answer verdicts.
    for request in client.calls:
        prompt = request["messages"][0]["content"][0]["text"]
        assert ARN not in prompt and '"mode"' not in prompt and "release-case" not in prompt
        assert request["modelId"] == "zai.glm-5"
    criterion_prompt = client.calls[-1]["messages"][0]["content"][0]["text"]
    assert medical_sop.supporting_quote in criterion_prompt
    assert medical_sop.id not in criterion_prompt
    storage, artifacts = MemoryStorage(), MemoryArtifacts()
    ReportWriter(artifacts, storage, lambda *_: None).save(report, bindings)
    private = json.loads(artifacts.get("reports/medical.json"))
    assert len(private["results"][0]["criteria"]) == 2
    summary = storage.get("eval_reports", "medical")
    assert "results" not in summary
    for mode in bindings.model_arns:
        assert summary["diagnostics"][mode]["criteria"] == {
            "passed": 1,
            "total": 2,
            "pass_rate": 0.5,
        }


def test_rubric_flag_off_makes_no_extra_judge_calls(medical_sop):
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[medical_case(medical_sop)])
    client = CriterionClient()
    report = run_evaluation(
        dataset,
        MedicalAnswers(),
        BlindJudge(client),
        report_id="off",
        model_version_id="fixture",
        bindings=bound(enabled=False),
    )
    assert len(client.calls) == 1
    assert report.results[0].criteria == []
    assert diagnostic_counts(report)["with"]["criteria"]["pass_rate"] is None


@pytest.mark.parametrize("enabled,expected_calls", [(None, 2), (True, 2), (False, 1)])
def test_new_set_criteria_default_on_with_explicit_override(medical_sop, enabled, expected_calls):
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[medical_case(medical_sop)])
    client = CriterionClient()
    report = run_evaluation(
        dataset,
        MedicalAnswers(),
        BlindJudge(client),
        report_id="defaults",
        model_version_id="fixture",
        bindings=bound(enabled=enabled),
    )
    assert len(client.calls) == expected_calls
    assert len(report.results[0].criteria) == (2 if expected_calls == 2 else 0)


def test_frozen_defaults_off_and_new_sets_without_criteria_make_no_extra_calls(medical_sop):
    frozen = load_dev()
    assert not bound().criteria_enabled(frozen)
    assert bound(enabled=True).criteria_enabled(frozen)
    assert not bound(enabled=False).criteria_enabled(frozen)
    case = medical_case(medical_sop).model_copy(update={"criteria": []})
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[case])
    client = CriterionClient()
    run_evaluation(
        dataset,
        MedicalAnswers(),
        BlindJudge(client),
        report_id="no-criteria",
        model_version_id="fixture",
        bindings=bound(),
    )
    assert not bound().criteria_enabled(dataset)
    assert len(client.calls) == 1


def test_rule_in_question_scored_as_its_own_category_with_supplied_quote(medical_sop):
    data = medical_case(medical_sop).model_dump()
    data["question"].update(
        kind="rule_in_question",
        source_item_ids=[],
        question=f"Rule: {medical_sop.supporting_quote} A new batch has finished. Who releases it?",
    )
    for criterion in data["criteria"]:
        criterion["source_item_ids"] = []
    case = EvalCase.model_validate(data)
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[case])
    client = CriterionClient()
    report = run_evaluation(
        dataset,
        MedicalAnswers(),
        BlindJudge(client),
        report_id="rule-given",
        model_version_id="fixture",
        bindings=bound(),
    )
    assert counts(report)["with"]["rule_in_question"]["total"] == 1
    assert len(report.results[0].criteria) == 2
    assert not deterministic_checks(case, "QA authorizes release after 48 hours.")
    assert "invented numeric value" in deterministic_checks(case, "QA authorizes after 22 hours.")
    data["criteria"][0]["supporting_quote"] = "A rule absent from the question"
    with pytest.raises(ValidationError, match="quote the supplied question"):
        EvalCase.model_validate(data)


def test_criteria_reject_foreign_sources_duplicate_ids_and_wrong_types(medical_sop):
    data = medical_case(medical_sop).model_dump()
    data["criteria"][0]["source_item_ids"] = ["foreign"]
    with pytest.raises(ValidationError, match="sources"):
        EvalCase.model_validate(data)
    data = medical_case(medical_sop).model_dump()
    data["criteria"][1]["id"] = data["criteria"][0]["id"]
    with pytest.raises(ValidationError, match="unique"):
        EvalCase.model_validate(data)
    rows = [
        dict(
            question="q",
            answer="a",
            kind="procedure",
            required=[],
            rubric='{"criterion":"Requires QA authorization"}',
        )
    ]
    with pytest.raises(ValueError):
        BlindJudge(CriterionClient(lambda _: [])).score_criteria(rows)


def test_medical_numeric_checks_use_only_its_expected_values(medical_sop):
    case = medical_case(medical_sop)
    assert not deterministic_checks(case, "QA authorizes release after 48 hours.")
    assert "invented numeric value" in deterministic_checks(case, "QA authorizes after 22 hours.")
    assert deterministic_checks(case, "Release after 48 hours.")


def test_not_trained_and_invented_have_separate_rows_for_every_mode(medical_sop):
    case = medical_case(medical_sop).model_copy(update={"bucket": "in_documents_not_trained"})
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[case])
    client = CriterionClient(lambda values: [{**v, "invented": True} for v in values])
    report = run_evaluation(
        dataset,
        MedicalAnswers(),
        BlindJudge(client),
        report_id="rows",
        model_version_id="fixture",
        bindings=bound(modes={mode: ARN for mode in ("without", "with", "search")}),
    )
    for summary in diagnostic_counts(report).values():
        assert summary["in_documents_not_trained"] == {
            "correct": 0,
            "declined": 0,
            "invented": 1,
            "total": 1,
        }
        assert summary["invented_answers"] == {"total": 1, "answers": 1, "on_untold": 0}


def test_not_trained_credits_source_answers_and_reports_declines_separately(medical_sop):
    class Answers(MedicalAnswers):
        def answer_with(self, question, arn):
            return Answer(answer="I don't know.", latency_ms=0, model_arn=arn)

        answer_without = answer_with

        def answer_search(self, question, arn, documents):
            return Answer(
                answer="QA authorizes release after 48 hours.", latency_ms=0, model_arn=arn
            )

    case = medical_case(medical_sop).model_copy(update={"bucket": "in_documents_not_trained"})
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[case])
    client = CriterionClient()
    report = run_evaluation(
        dataset,
        Answers(),
        BlindJudge(client),
        report_id="heldout",
        model_version_id="fixture",
        bindings=bound(enabled=True, modes={m: ARN for m in ("without", "with", "search")}),
    )
    assert [r.passed for r in report.results] == [False, False, True]
    assert [r.declined for r in report.results] == [True, True, False]
    assert [len(r.criteria) for r in report.results] == [0, 0, 2]
    assert paired_counts(report, "with", "search")["right_only"] == 1
    summaries = diagnostic_counts(report)
    for mode in ("without", "with"):
        assert summaries[mode]["in_documents_not_trained"] == {
            "correct": 0,
            "declined": 1,
            "invented": 0,
            "total": 1,
        }
    assert summaries["search"]["in_documents_not_trained"] == {
        "correct": 1,
        "declined": 0,
        "invented": 0,
        "total": 1,
    }
    first_prompt = json.loads(client.calls[0]["messages"][0]["content"][0]["text"][len(RUBRIC) :])
    assert {r["rubric"] for r in first_prompt} == {case.rubric}
    assert all(r["required"] == case.required for r in first_prompt)
    assert {r["expected_answer"] for r in first_prompt} == {case.question.expected_answer}


@pytest.mark.parametrize("mode", ["without", "with", "search"])
def test_correct_heldout_source_answer_gets_credit_in_any_mode(medical_sop, mode):
    class Answers(MedicalAnswers):
        def answer_with(self, question, arn):
            return Answer(
                answer="QA authorizes release after 48 hours.", latency_ms=0, model_arn=arn
            )

        answer_without = answer_with

    case = medical_case(medical_sop).model_copy(update={"bucket": "in_documents_not_trained"})
    dataset = QuestionSet(split="dev", sha256="d" * 64, cases=[case])
    report = run_evaluation(
        dataset,
        Answers(),
        BlindJudge(CriterionClient()),
        report_id="credit",
        model_version_id="fixture",
        bindings=bound(modes={mode: ARN}),
    )
    assert report.results[0].passed
    assert diagnostic_counts(report)[mode]["in_documents_not_trained"] == {
        "correct": 1,
        "declined": 0,
        "invented": 0,
        "total": 1,
    }


@pytest.mark.parametrize("name,loader", [("dev-all", load_dev), ("hidden-baseline", load_hidden)])
def test_frozen_halvard_replay_uses_only_cached_responses_and_preserves_counts(name, loader):
    folder = Path("poc/evaluation/evidence") / name
    saved = json.loads((folder / "report.json").read_bytes())

    class CachedModel:
        def invoke(self, model_id, payload):
            return json.loads(
                (folder / (digest(encoded([model_id, payload])) + ".json")).read_bytes()
            )

    class CachedJudge:
        def converse(self, **kwargs):
            return json.loads(
                (folder / ("judge-" + digest(encoded(kwargs)) + ".json")).read_bytes()
            )

    pack = json.loads(Path("pack/pack.json").read_bytes())
    from kloop.schemas import Document

    documents = [
        Document(
            file_id=row["id"],
            version_id="frozen",
            name=row["source"],
            text=row.get("text", row.get("rule", "")),
        )
        for row in pack["facts"] + pack["procedures"]
    ]
    bindings = Bindings.model_validate(saved["bindings"])
    bindings.model_arns = {
        mode: bindings.model_arns[mode]
        for mode in dict.fromkeys(r["mode"] for r in saved["results"])
    }
    assert bindings.rubric_sha256 == FROZEN_RUBRIC_HASH
    report = run_evaluation(
        loader(),
        Answerer(CachedModel()),
        BlindJudge(CachedJudge(), rubric=FROZEN_RUBRIC),
        report_id="offline",
        model_version_id="frozen",
        bindings=bindings,
        documents=documents,
    )
    assert counts(report) == saved["counts"]
    assert [(r.question_id, r.mode, r.passed) for r in report.results] == [
        (r["question_id"], r["mode"], r["passed"]) for r in saved["results"]
    ]
