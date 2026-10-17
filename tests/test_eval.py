import json
from pathlib import Path

import pytest

from kloop.adapters.memory import MemoryArtifacts, MemoryStorage
from kloop.answer import Answer, Answerer
from kloop.eval import (
    Bindings,
    Evaluator,
    ReportWriter,
    counts,
    deterministic_checks,
    paired_counts,
    promotion_gate,
    run_evaluation,
)
from kloop.eval.datasets import (
    DEV_HASH,
    EvalCase,
    QuestionSet,
    digest,
    lexical_audit,
    load_dev,
    load_hidden,
    verified_rows,
)
from kloop.eval.judge import RUBRIC, BlindJudge, Verdict
from kloop.schemas import EvalReport, EvalResult, Question

ARN = "arn:aws:bedrock:us-east-2:123456789012:imported-model/0inmdc8ttj1w"


class JudgeClient:
    def __init__(self, mutate=lambda values: values):
        self.calls = []
        self.mutate = mutate

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][0]["content"][0]["text"]
        rows = json.loads(prompt[len(RUBRIC) :])
        values = [
            dict(id=row["id"], correct=True, invented=False, reason="correct") for row in rows
        ]
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": json.dumps(self.mutate(values))}]}},
            "usage": {"inputTokens": 10},
        }


def bindings(modes=None):
    return Bindings(
        corpus_sha256="c" * 64,
        audit_sha256="a" * 64,
        manifest_sha256="b" * 64,
        model_arns=modes or {"with": ARN},
        serving_version="v1",
    )


def report(passes, *, split="dev"):
    cases = load_dev().cases
    return EvalReport(
        id="fake",
        model_version_id="v1",
        split=split,
        question_set_sha256=DEV_HASH,
        results=[
            EvalResult(
                question_id=c.question.id,
                kind=c.question.kind,
                mode="with",
                answer="private",
                passed=i in passes,
                score=float(i in passes),
            )
            for i, c in enumerate(cases)
        ],
    )


def test_frozen_inputs_and_hash_failure(tmp_path):
    dev, hidden = load_dev(), load_hidden()
    assert len(dev.cases) == 30
    assert sum(c.question.kind == "untold" for c in dev.cases) == 8
    assert len(hidden.cases) == 52
    assert all(c.question.split == "hidden" for c in hidden.cases)
    path = tmp_path / "dev.jsonl"
    path.write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_dev(path)
    with pytest.raises(ValueError, match="hash mismatch"):
        verified_rows(Path("pack/sealed/hidden.jsonl"), "0" * 64)


def test_blind_judge_strips_identities_and_shuffles():
    client = JudgeClient()
    rows = [
        dict(
            question=f"question {i}",
            answer="text",
            rubric="rule",
            required=[],
            kind="fact",
            mode="with",
            model_arn=ARN,
            id=f"original-{i}",
        )
        for i in range(12)
    ]
    result = BlindJudge(client).score(rows)
    assert len(result) == 12
    prompts = [r["messages"][0]["content"][0]["text"] for r in client.calls]
    assert all(ARN not in p and '"mode"' not in p and "original-" not in p for p in prompts)
    questions = [r["question"] for r in json.loads(prompts[0][len(RUBRIC) :])]
    assert questions != [r["question"] for r in rows[:10]]
    assert all(
        r["modelId"] == "zai.glm-5" and r["inferenceConfig"]["maxTokens"] == 3072
        for r in client.calls
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows[:-1],
        lambda rows: rows + rows,
        lambda rows: [{**rows[0], "correct": "true"}],
    ],
)
def test_judge_fails_closed(mutate):
    rows = [dict(question="q", answer="a", rubric="r", required=[], kind="fact")]
    with pytest.raises(ValueError):
        BlindJudge(JudgeClient(mutate)).score(rows)


def test_code_checks_veto_semantic_pass():
    case = EvalCase(
        question=Question(
            id="x", question="Sable limit?", expected_answer="96 GB", kind="fact", split="dev"
        ),
        rubric="value",
        required=["96 GB"],
        forbidden=["73 GB"],
    )
    reasons = deterministic_checks(case, "73 GB; extra 450 GB")
    assert any("missing required" in r for r in reasons)
    assert "invented numeric value" in reasons
    assert "retired/stale value: 73 GB" in reasons
    unknown = case.model_copy(
        update={
            "question": case.question.model_copy(update={"kind": "untold"}),
            "required": [],
            "forbidden": [],
        }
    )
    assert deterministic_checks(unknown, "The answer is main.")
    assert not deterministic_checks(unknown, "I don't know.")
    procedure = case.model_copy(
        update={
            "question": case.question.model_copy(update={"kind": "procedure"}),
            "procedure_id": "P01",
            "forbidden": [],
        }
    )
    assert deterministic_checks(procedure, "Replace immediately.")
    assert not deterministic_checks(
        procedure, "Restore inlet pressure to 4 bar and retest. Only replace if E42 persists."
    )


def test_gate_strict_gain_and_protected_regressions():
    cases = load_dev().cases
    protected = {i for i, c in enumerate(cases) if c.question.kind in {"untold", "unrelated"}}
    fact = next(i for i, c in enumerate(cases) if c.question.kind == "fact")
    decision = promotion_gate(report(protected), report(protected | {fact}), report_uri="reports/x")
    assert decision.passed and decision.counts["total"] == 30
    assert not promotion_gate(report(protected), report(protected), report_uri="r").passed
    # Gain overall still cannot compensate for a new protected failure.
    changed = set(range(30)) - {min(protected)}
    decision = promotion_gate(report(protected), report(changed), report_uri="r")
    assert not decision.passed and decision.counts["protected_regressions"] == 1
    with pytest.raises(ValueError, match="frozen dev"):
        promotion_gate(report(set(), split="hidden"), report(set()), report_uri="r")
    partial = report(set())
    partial.results.pop()
    with pytest.raises(ValueError):
        promotion_gate(partial, partial, report_uri="r")


def test_audit_hash_bound_no_hidden_content():
    hidden = load_hidden()
    training = json.dumps(
        {
            "messages": [
                {"role": "system", "content": "s"},
                {"role": "user", "content": hidden.cases[0].question.question},
            ]
        }
    ).encode()
    result = lexical_audit(training, hidden, immutable_training_hash=digest(training))
    assert not result["passed"] and result["collisions"] >= 1
    assert hidden.cases[0].question.question not in json.dumps(result)
    assert "sha256" in result
    with pytest.raises(ValueError):
        lexical_audit(training, hidden, immutable_training_hash="0" * 64)


def test_report_public_summary_has_no_hidden_answers():
    private = report({0}, split="hidden")
    storage, artifacts, box = MemoryStorage(), MemoryArtifacts(), {}
    writer = ReportWriter(artifacts, storage, lambda name, data: box.update({name: data}))
    assert writer.save(private, bindings()) == "sealed/reports/fake.json"
    summary = storage.get("eval_reports", "fake")
    assert "results" not in summary and "private" not in json.dumps(summary)
    assert "private" not in box["fake.json"].decode()
    assert b'"answer": "private"' in artifacts.get("sealed/reports/fake.json")
    assert summary["counts"]["with"]["fact"]["total"] > 0
    assert len(summary["caveats"]) >= 6


def test_writer_does_not_publish_on_box_failure():
    def fail(*args):
        raise RuntimeError("Box failed")

    storage = MemoryStorage()
    with pytest.raises(RuntimeError):
        ReportWriter(MemoryArtifacts(), storage, fail).save(report(set()), bindings())
    assert not storage.list("eval_reports")


def test_run_and_pipeline_adapter_use_fakes():
    dataset = load_dev()
    expected = {c.question.question: c.question.expected_answer for c in dataset.cases}

    class FakeAnswers:
        def answer_without(self, question, arn):
            return Answer(answer="wrong", latency_ms=0, model_arn=arn)

        def answer_with(self, question, arn):
            return Answer(answer=expected[question], latency_ms=0, model_arn=arn)

    storage, artifacts = MemoryStorage(), MemoryArtifacts()
    evaluator = Evaluator(
        FakeAnswers(),
        BlindJudge(JudgeClient()),
        ReportWriter(artifacts, storage, lambda *_: None),
        current_arn=lambda _: ARN,
        audit_hash=lambda *_: "a" * 64,
    )
    result = evaluator.evaluate(ARN, "c" * 64, "b" * 64, "v1", DEV_HASH)
    assert result.passed and result.counts["candidate"] > result.counts["current"]
    assert len(storage.list("eval_reports")) == 2
    assert json.loads(artifacts.get(result.report_uri))["gate"]["passed"]
    with pytest.raises(ValueError):
        evaluator.evaluate(ARN, "c" * 64, "b" * 64, "v1", "wrong")


def test_run_checks_before_judge_and_pairs_counts():
    case = load_dev().cases[0]
    dataset = QuestionSet(split="dev", sha256=DEV_HASH, cases=[case])

    class Client:
        def invoke(self, model_id, payload):
            return {"generation": "Wrong value"}

    class Judge:
        def score(self, rows):
            return [Verdict(id="x", correct=True, invented=False, reason="pass") for _ in rows]

    result = run_evaluation(
        dataset,
        Answerer(Client()),
        Judge(),
        report_id="r",
        model_version_id="v1",
        bindings=bindings({"without": ARN, "with": ARN}),
    )
    assert all(not r.passed for r in result.results)
    assert paired_counts(result, "without", "with")["both_wrong"] == 1
    assert counts(result)["with"]["fact"]["correct"] == 0
    result.results.pop()
    with pytest.raises(ValueError):
        paired_counts(result, "without", "with")


def test_minimum_gain_and_version_probes():
    from kloop.eval.datasets import load_version_probes

    assert not promotion_gate(report(set()), report({0}), report_uri="r", minimum_gain=0.05).passed
    assert promotion_gate(report(set()), report({0, 1}), report_uri="r", minimum_gain=0.05).passed
    with pytest.raises(ValueError):
        promotion_gate(report(set()), report({0}), report_uri="r", minimum_gain=float("nan"))
    v1, v2 = load_version_probes("v1"), load_version_probes("v2")
    assert len(v1.cases) == len(v2.cases) == 2
    assert v1.sha256 != v2.sha256
    assert deterministic_checks(v2.cases[0], "73 GB")
    assert not deterministic_checks(v2.cases[0], "96 GB")
    assert deterministic_checks(v2.cases[1], "I don't know; pick it up at Q-14.")


def test_runtime_audit_rechecks_immutable_manifest_and_training():
    from kloop.answer import SYSTEM_PROMPT
    from kloop.eval.datasets import encoded
    from kloop.eval.runtime import AuditVerifier

    artifacts = MemoryArtifacts()
    for name in ["hidden.jsonl", "addendum-v2.jsonl"]:
        artifacts.put(f"sealed/{name}", Path("pack/sealed", name).read_bytes())
    training = (
        encoded(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "Explain multiplication of integers."},
                    {"role": "assistant", "content": "Repeated addition."},
                ]
            }
        )
        + b"\n"
    )
    manifest = dict(
        snapshot_hash="c" * 64,
        dev_set_hash=DEV_HASH,
        system_prompt_sha256=digest(SYSTEM_PROMPT.encode()),
        train_sha256=digest(training),
    )
    data = encoded(manifest)
    sha = digest(data)
    artifacts.put(f"training/data/{sha}/manifest.json", data)
    artifacts.put(f"training/data/{sha}/train.jsonl", training)
    verifier = AuditVerifier(artifacts)
    audit_hash = verifier.verify(sha, "c" * 64)
    value = json.loads(artifacts.get(f"evaluations/audits/{audit_hash}.json"))
    assert value["passed"] and value["training_sha256"] == digest(training)
    with pytest.raises(ValueError, match="bindings"):
        verifier.verify(sha, "d" * 64)
    artifacts.put(f"training/data/{sha}/train.jsonl", b"changed")
    with pytest.raises(ValueError, match="immutable"):
        verifier.verify(sha, "c" * 64)


def test_judge_accepts_single_json_fence_but_not_surrounding_prose():
    class FencedClient(JudgeClient):
        def converse(self, **kwargs):
            result = super().converse(**kwargs)
            block = result["output"]["message"]["content"][0]
            block["text"] = "```json\n" + block["text"] + "\n```"
            return result

    rows = [dict(question="q", answer="a", rubric="r", required=[], kind="fact")]
    assert BlindJudge(FencedClient()).score(rows)[0].correct


def test_report_retry_cannot_replace_immutable_evidence():
    storage, artifacts = MemoryStorage(), MemoryArtifacts()
    writer = ReportWriter(artifacts, storage, lambda *_: None)
    original = report({0})
    writer.save(original, bindings())
    before = artifacts.get("reports/fake.json")
    writer.save(original, bindings())
    with pytest.raises(ValueError, match="immutable"):
        writer.save(report({0, 1}), bindings())
    assert artifacts.get("reports/fake.json") == before


def test_value_checks_allow_sentence_order_without_dropping_values():
    case = EvalCase(
        question=Question(
            id="x", question="When and where?", expected_answer="", kind="two_fact", split="dev"
        ),
        rubric="both values",
        required=["02:40 UTC every Tuesday", "cabinet Q-14"],
    )
    assert not deterministic_checks(case, "Every Tuesday at 02:40 UTC; the cabinet label is Q-14.")
    assert deterministic_checks(case, "Every Thursday at 02:40 UTC; the cabinet label is Q-14.")
    assert deterministic_checks(case, "Every Tuesday at 02:40 UTC; the cabinet label is Q-13.")
