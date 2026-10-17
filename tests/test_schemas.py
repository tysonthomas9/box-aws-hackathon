import pytest
from pydantic import ValidationError

from kloop.schemas import AskJob, Document, EvalReport, EvalResult, Item, ModelVersion, Question


@pytest.mark.parametrize(
    "value",
    [
        Document(file_id="1", version_id="2", name="Policy", text="A policy — 雪"),
        Item(
            id="i1",
            kind="fact",
            subject="Support",
            statement="Call Mara",
            supporting_quote="Call Mara",
            source_file_id="1",
            source_version_id="2",
            extractor="box-ai/pinned",
        ),
        Item(
            id="i2",
            kind="procedure",
            subject="Incident",
            statement="Escalate",
            trigger_conditions=["Severity 1"],
            steps=["Page Mara", "Open a bridge"],
            supporting_quote="Page Mara",
            source_file_id="1",
            source_version_id="2",
            extractor="box-ai/pinned",
            status="flagged",
            flag_reasons=["Needs review"],
        ),
        Question(id="q1", question="Who?", expected_answer="Mara", kind="fact", split="hidden"),
        ModelVersion(
            id="v1",
            import_arn="arn:aws:bedrock:us-east-2:123456789012:imported-model/test",
            status="ready",
            manifest={"items": ["i1"], "seed": 17},
            scores={"dev": 0.8},
        ),
        AskJob(
            id="j1", question="Who?", mode="with", status="completed", answer="Mara", latency_ms=3.5
        ),
        EvalReport(
            id="e1",
            model_version_id="v1",
            split="hidden",
            question_set_sha256="a" * 64,
            results=[
                EvalResult(
                    question_id="q1", kind="fact", mode="with", answer="Mara", passed=True, score=1
                )
            ],
            scores={"fact": 1.0},
        ),
    ],
)
def test_schema_json_round_trip(value):
    assert type(value).model_validate_json(value.model_dump_json()) == value
    assert type(value).model_json_schema()["additionalProperties"] is False


def test_invalid_payloads_fail_visibly():
    with pytest.raises(ValidationError):
        Document(file_id="1", version_id="2", name="Policy", text="", stale_field=True)
    with pytest.raises(ValidationError):
        AskJob(id="j", question="Who?", mode="unknown")
    with pytest.raises(ValidationError):
        AskJob(id="j", question="Who?", mode="with", latency_ms=-1)
    with pytest.raises(ValidationError):
        Question(id="q", question="Who?", expected_answer="Mara", kind="fact", split="test")
