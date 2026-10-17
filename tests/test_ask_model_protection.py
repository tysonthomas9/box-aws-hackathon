import pytest
from pydantic import ValidationError

from kloop.schemas import AskJob, PinnedModel
from kloop.train.resources import protected_ask_models

BASE = "arn:aws:bedrock:us-east-2:123456789012:imported-model/aaaaaaaaaaaa"
TRAINED = "arn:aws:bedrock:us-east-2:123456789012:imported-model/bbbbbbbbbbbb"


def job_payload(status="running", expires_at=200):
    job = AskJob(
        id="ask-1",
        question="Policy date?",
        mode="search",
        model_arn=BASE,
        model_version_id="base",
        snapshot_sha256="a" * 64,
        created_at=100,
        expires_at=expires_at,
        status=status,
        warm_up_models=[PinnedModel(model_arn=TRAINED, model_version_id="trained")],
    )
    return {
        **job.model_dump(mode="json"),
        "queue_ms": 1,
        "retrieval_ms": 2,
        "generation_ms": 3,
        "retriever": "box_search",
        "future_optional_answer_details": {"cache_hit": True, "attempt_durations": [1, 2]},
    }


@pytest.mark.parametrize(
    ("status", "expires", "expected"),
    [
        ("queued", 200, {BASE, TRAINED}),
        ("running", 200, {BASE, TRAINED}),
        ("warming", 200, {BASE, TRAINED}),
        ("succeeded", 200, set()),
        ("failed", 200, set()),
        ("running", 150, set()),
    ],
)
def test_model_protection_ignores_future_optional_job_fields(storage, status, expires, expected):
    storage.put("ask_jobs", "ask-1", job_payload(status, expires))
    assert protected_ask_models(storage, 150) == expected


@pytest.mark.parametrize("field,value", [("model_arn", "invalid"), ("expires_at", -1)])
def test_model_protection_still_validates_required_ownership_fields(storage, field, value):
    payload = job_payload()
    payload[field] = value
    storage.put("ask_jobs", "ask-1", payload)
    with pytest.raises(ValidationError):
        protected_ask_models(storage, 150)


def test_optional_reader_tolerance_does_not_relax_the_shared_ask_contract():
    with pytest.raises(ValidationError, match="future_optional_answer_details"):
        AskJob.model_validate(job_payload())
