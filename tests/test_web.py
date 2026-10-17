import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from kloop.answer import ModelWarming
from kloop.schemas import ApprovedSnapshot, Document, ExtractionRow, Item, ModelVersion, Review
from kloop.web.api import Services, create_app
from kloop.web.jobs import BUDGET, DynamoJobs, JobService, MemoryJobs, SearchEvidence, Worker
from kloop.web.security import COOKIE, DynamoThrottle, MemoryThrottle, Security

BASE = "arn:aws:bedrock:us-east-2:123456789012:imported-model/abcdefghijkl"
TRAINED = "arn:aws:bedrock:us-east-2:123456789012:imported-model/mnopqrstuvwx"
NOW = 1_792_221_000
ORIGIN = "https://example.cloudfront.net"


@pytest.fixture
def clock():
    now = [NOW]
    return SimpleNamespace(
        now=now, read=lambda: now[0], sleep=lambda n: now.__setitem__(0, now[0] + n)
    )


@pytest.fixture
def table(aws_session):
    return aws_session.resource("dynamodb").create_table(
        TableName="web-test",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture(params=["memory", "dynamo"])
def jobstore(request, table):
    return MemoryJobs() if request.param == "memory" else DynamoJobs(table)


@pytest.fixture
def setup(clock):
    security = Security("demo-password", "s" * 48, "o" * 48, ORIGIN)
    item = Item(
        id="i",
        attribute_id="a",
        subject="Pump",
        kind="fact",
        statement="Old value",
        supporting_quote="Old value",
        source_file_id="f",
        source_version_id="v1",
        extractor="fake",
        status="approved",
    )
    review = Review(
        id="r",
        item_id="i",
        attribute_id="a",
        source_file_id="f",
        source_version_id="v2",
        extractor="fake",
        candidate=ExtractionRow(
            kind="fact",
            subject="Pump",
            attribute="setting",
            statement="New value",
            supporting_quote="New value",
        ),
        reasons=["changed_value"],
    )
    extraction = Mock()
    extraction.snapshot.return_value = ApprovedSnapshot(sha256="a" * 64, items=[item])
    extraction.reviews.return_value = [review]
    extraction.get_review_mode.return_value = "exceptions"
    extraction.decide.return_value = review
    models = {
        "without": {"arn": BASE, "version_id": "base", "snapshot_sha256": None},
        "with": {"arn": TRAINED, "version_id": "v1", "snapshot_sha256": "b" * 64},
        "search": {"arn": BASE, "version_id": "base", "snapshot_sha256": None},
    }
    dispatch = Mock()
    jobs = JobService(MemoryJobs(), dispatch, clock=clock.read)
    training = Mock()
    training.versions.return_value = [
        ModelVersion(
            id="v1", import_arn=TRAINED, status="promoted", manifest={"snapshot_hash": "b" * 64}
        )
    ]
    training.start.return_value = ModelVersion(id="v2", status="training")
    training.status.return_value = ModelVersion(id="v2", status="importing")
    results = [
        {
            "id": "e",
            "model_version_id": "v1",
            "split": "hidden",
            "question_set_sha256": "c" * 64,
            "scores": {"with.fact": 0.9},
            "results": [{"answer": "PRIVATE"}],
            "questions": ["PRIVATE"],
        }
    ]
    ingress = Mock()
    ingress.webhook.return_value = {"statusCode": 403, "body": "Invalid signature"}
    services = Services(
        extraction,
        jobs,
        lambda: models,
        lambda: {"files": [], "runs": []},
        ingress,
        training,
        lambda: results,
    )
    client = TestClient(
        create_app(services, security, MemoryThrottle(), clock=clock.read), base_url=ORIGIN
    )
    client.headers["X-Kloop-Origin"] = security.origin_key
    client.headers["Origin"] = ORIGIN
    return SimpleNamespace(
        client=client,
        security=security,
        services=services,
        models=models,
        dispatch=dispatch,
        clock=clock,
    )


def login(setup):
    r = setup.client.post("/api/login", json={"password": "demo-password"})
    assert r.status_code == 200
    setup.client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r


ROUTES = [
    ("GET", "/api/session", None),
    ("POST", "/api/logout", {}),
    ("GET", "/api/sources", None),
    ("POST", "/api/sync", {}),
    ("GET", "/api/reviews", None),
    ("POST", "/api/reviews/r", {"action": "approve"}),
    ("POST", "/api/review-mode", {"mode": "all"}),
    ("GET", "/api/serving", None),
    ("POST", "/api/ask", {"question": "Who?"}),
    ("POST", "/api/warm-up", {}),
    ("GET", "/api/jobs/missing", None),
    ("POST", "/api/train", {"request_id": "request-1"}),
    ("GET", "/api/training", None),
    ("GET", "/api/training/v1", None),
    ("GET", "/api/results", None),
    ("GET", "/openapi.json", None),
    ("GET", "/docs", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_routes_require_valid_cookie(setup, method, path, body):
    assert setup.client.request(method, path, json=body).status_code == 401
    login(setup)
    setup.clock.now[0] += 3601
    assert setup.client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize("method,path,body", [r for r in ROUTES if r[0] == "POST"])
def test_every_write_needs_origin_and_csrf(setup, method, path, body):
    login(setup)
    setup.client.headers.pop("X-CSRF-Token")
    assert setup.client.request(method, path, json=body).status_code == 403
    setup.client.headers["X-CSRF-Token"] = "wrong"
    assert setup.client.request(method, path, json=body).status_code == 403
    setup.client.headers.pop("Origin")
    assert setup.client.request(method, path, json=body).status_code == 403


def test_login_cookie_tampering_and_direct_origin_guard(setup):
    client = setup.client
    client.headers.pop("X-Kloop-Origin")
    assert client.post("/api/login", json={"password": "demo-password"}).status_code == 403
    client.headers["X-Kloop-Origin"] = setup.security.origin_key
    client.headers["Origin"] = "https://evil.example"
    assert client.post("/api/login", json={"password": "demo-password"}).status_code == 403
    client.headers["Origin"] = ORIGIN
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    r = login(setup)
    cookie = r.headers["set-cookie"]
    assert all(
        flag in cookie
        for flag in ("Secure", "HttpOnly", "SameSite=strict", "Path=/", "Max-Age=3600")
    )
    assert "Domain=" not in cookie
    assert r.headers["cache-control"] == "no-store"
    assert client.get("/api/session").json()["csrf_token"] == r.json()["csrf_token"]
    token = setup.security.issue(NOW)[0]
    client.cookies.clear()
    client.cookies.set(COOKIE, token[:-1] + ("a" if token[-1] != "a" else "b"))
    assert client.get("/api/session").status_code == 401
    assert (
        "demo-password" not in client.post("/api/login", json={"password": ["demo-password"]}).text
    )


def test_throttling_cannot_be_bypassed_with_forwarded_ip(setup):
    for n in range(10):
        assert (
            setup.client.post(
                "/api/login", json={"password": "bad"}, headers={"X-Forwarded-For": str(n)}
            ).status_code
            == 401
        )
    assert setup.client.post("/api/login", json={"password": "demo-password"}).status_code == 429
    setup.clock.now[0] += 60
    login(setup)


def test_all_screens_and_comparison_pins(setup):
    login(setup)
    client = setup.client
    assert client.get("/api/sources").json() == {"files": [], "runs": []}
    assert client.post("/api/sync", json={}).status_code == 202
    reviews = client.get("/api/reviews").json()
    assert reviews["reviews"][0]["previous"]["statement"] == "Old value"
    assert reviews["reviews"][0]["candidate"]["statement"] == "New value"
    assert client.post("/api/reviews/r", json={"action": "approve"}).status_code == 200
    assert client.post("/api/review-mode", json={"mode": "all"}).status_code == 200
    assert client.get("/api/serving").json()["stale"] is True
    setup.models["with"]["snapshot_sha256"] = "a" * 64
    assert client.get("/api/serving").json()["stale"] is False
    response = client.post("/api/ask", json={"question": "Who?"})
    assert response.status_code == 202
    rows = response.json()["jobs"]
    assert len(rows) == 3
    setup.models["with"]["arn"] = BASE
    assert client.get("/api/jobs/" + rows[1]["id"]).json()["model_arn"] == TRAINED
    assert all(row["snapshot_sha256"] == "a" * 64 for row in rows)
    assert client.post("/api/ask", json={"question": "  "}).status_code == 422
    assert client.post("/api/ask", json={"question": "a" * 2001}).status_code == 422
    assert len(client.post("/api/warm-up", json={}).json()["jobs"]) == 1
    assert (
        client.post("/api/train", json={"request_id": "request-1"}).json()["status"] == "training"
    )
    setup.services.training.start.assert_called_once_with("request-1", NOW)
    assert client.get("/api/training/v2").json()["status"] == "importing"
    assert "PRIVATE" not in client.get("/api/results").text
    assert client.post("/api/logout", json={}).status_code == 200
    assert client.get("/api/session").status_code == 401


def test_unavailable_trained_model_is_explicit(setup):
    login(setup)
    setup.models["with"] = None
    value = setup.client.post("/api/ask", json={"question": "Who?"}).json()
    assert value["unavailable"] == ["with"]
    assert {j["mode"] for j in value["jobs"]} == {"without", "search"}


def test_job_redelivery_cold_start_and_immutable_arn(jobstore, clock):
    dispatch = Mock()
    jobs = JobService(jobstore, dispatch, clock=clock.read)
    job = jobs.create("Who?", "with", TRAINED, "v1", "a" * 64)
    statuses = []
    model = Mock()

    def invoke(arn, payload):
        statuses.append(jobs.get(job.id).status)
        assert arn == TRAINED
        if len(statuses) < 3:
            raise ModelWarming
        return {"generation": "Mara"}

    model.invoke.side_effect = invoke
    worker = Worker(jobs, model, Mock(), clock=clock.read, sleep=clock.sleep)
    event = {"Records": [{"messageId": "m", "body": json.dumps({"job_id": job.id})}]}
    assert worker.handle(event) == {"batchItemFailures": []}
    assert worker.handle(event) == {"batchItemFailures": []}
    result = jobs.get(job.id)
    assert statuses == ["running", "warming", "warming"]
    assert result.status == "succeeded" and result.answer == "Mara" and result.attempts == 1
    assert model.invoke.call_count == 3
    assert result.latency_ms == 6000


def test_search_and_warm_up_use_answerer(jobstore, clock):
    jobs = JobService(jobstore, Mock(), clock=clock.read)
    model = Mock()
    model.invoke.return_value = {"generation": "Mara [1]"}
    docs = Mock(
        return_value=SearchEvidence(
            [Document(file_id="f", version_id="v", name="Support", text="Mara handles support.")],
            {("f", "v"): ["Mara handles support."]},
        )
    )
    worker = Worker(jobs, model, docs, clock=clock.read, sleep=clock.sleep)
    job = jobs.create("Who handles support?", "search", BASE, "base", "a" * 64)
    worker.run(job.id)
    result = jobs.get(job.id)
    assert result.citations[0]["file_id"] == "f"
    docs.assert_called_once_with("a" * 64)
    warm = jobs.create("READY", "without", BASE, "base", "a" * 64, warm_up=True)
    worker.run(warm.id)
    assert model.invoke.call_args.args[1]["max_gen_len"] == 16


def test_expiry_queue_failure_and_sanitized_errors(jobstore, clock):
    jobs = JobService(jobstore, Mock(), clock=clock.read)
    job = jobs.create("Who?", "without", BASE, "base", "a" * 64)
    model = Mock()
    clock.now[0] += BUDGET + 1
    worker = Worker(jobs, model, Mock(), clock=clock.read, sleep=clock.sleep)
    worker.run(job.id)
    assert jobs.get(job.id).status == "failed"
    model.invoke.assert_not_called()
    job = jobs.create("Who?", "without", BASE, "base", "a" * 64)
    model.invoke.side_effect = RuntimeError("TOP SECRET")
    worker.run(job.id)
    assert jobs.get(job.id).status == "failed"
    assert "TOP SECRET" not in jobs.get(job.id).model_dump_json()
    jobs.dispatch.side_effect = RuntimeError("TOP SECRET")
    with pytest.raises(RuntimeError, match="Queue unavailable"):
        jobs.create("Who?", "without", BASE, "base", "a" * 64)


def test_cas_lost_claim_and_crashed_worker_are_bounded(jobstore, clock):
    jobs = JobService(jobstore, Mock(), clock=clock.read)
    job = jobs.create("Who?", "without", BASE, "base", "a" * 64)
    first, revision = jobstore.read(job.id)
    second, _ = jobstore.read(job.id)
    first.status = "running"
    assert jobstore.save(first, revision)
    assert not jobstore.save(second, revision)
    model = Mock()
    worker = Worker(jobs, model, Mock(), clock=clock.read, sleep=clock.sleep)
    worker.run(job.id)
    model.invoke.assert_not_called()
    clock.now[0] += BUDGET + 1
    assert jobs.get(job.id).status == "failed"


def test_failed_storage_returns_sqs_partial_batch_failure(clock):
    store = Mock()
    store.read.side_effect = RuntimeError("storage down")
    worker = Worker(JobService(store, Mock(), clock=clock.read), Mock(), Mock())
    assert worker.handle({"Records": [{"messageId": "m", "body": '{"job_id":"j"}'}]}) == {
        "batchItemFailures": [{"itemIdentifier": "m"}]
    }


def test_dynamo_throttle_counts_shared_across_instances(table):
    a, b = DynamoThrottle(table), DynamoThrottle(table)
    assert a.allow("login:ip", 2, NOW)
    assert b.allow("login:ip", 2, NOW)
    assert not a.allow("login:ip", 2, NOW)
    assert a.allow("login:ip", 2, NOW + 60)


def test_webhook_signature_only_through_api(setup):
    from kloop.box.webhooks import verify_webhook

    now = datetime.fromtimestamp(NOW, UTC)
    timestamp = now.isoformat()
    raw = b'{"id":"event"}'
    signature = base64.b64encode(
        hmac.digest(b"key", raw + timestamp.encode(), hashlib.sha256)
    ).decode()

    def webhook(req):
        valid = verify_webhook(
            base64.b64decode(req["body"]), req["headers"], primary_key="key", now=now
        )
        return {
            "statusCode": 202 if valid else 403,
            "body": "Accepted" if valid else "Invalid signature",
        }

    setup.services.ingress.webhook.side_effect = webhook
    setup.client.headers.pop("Origin")
    assert setup.client.post("/api/box-webhook", content=raw).status_code == 403
    headers = {"Box-Delivery-Timestamp": timestamp, "Box-Signature-Primary": signature}
    assert setup.client.post("/api/box-webhook", content=raw, headers=headers).status_code == 202
    assert (
        setup.client.post("/api/box-webhook", content=raw + b" ", headers=headers).status_code
        == 403
    )


def test_runtime_modules_import_without_credentials(monkeypatch):
    import importlib

    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for module in ("kloop.web.runtime", "lambdas.api", "lambdas.ask_worker"):
        importlib.import_module(module)


def test_fifteen_minute_readiness_and_sequential_warm_up(jobstore, clock):
    from kloop.schemas import PinnedModel

    jobs = JobService(jobstore, Mock(), clock=clock.read)
    pins = [
        PinnedModel(model_arn=arn, model_version_id=version)
        for arn, version in ((BASE, "base"), (TRAINED, "v1"))
    ]
    warm = jobs.create(
        "READY", "without", BASE, "base", "a" * 64, warm_up=True, warm_up_models=pins
    )
    assert warm.expires_at - warm.created_at == 900
    with pytest.raises(ValueError, match="already active"):
        jobs.create("READY", "without", BASE, "base", "a" * 64, warm_up=True)
    calls = []

    def invoke(arn, payload):
        calls.append(arn)
        assert jobs.get(warm.id).status == "warming"
        if arn == BASE and clock.read() < NOW + 300:
            raise ModelWarming
        if arn == TRAINED and clock.read() < NOW + 600:
            raise ModelWarming
        return {"generation": "READY"}

    model = Mock()
    model.invoke.side_effect = invoke
    worker = Worker(jobs, model, Mock(), clock=clock.read, sleep=clock.sleep)
    worker.run(warm.id)
    result = jobs.get(warm.id)
    assert result.status == "succeeded"
    assert 600_000 <= result.latency_ms < 900_000
    first_trained = calls.index(TRAINED)
    assert all(arn == BASE for arn in calls[:first_trained])
    assert all(arn == TRAINED for arn in calls[first_trained:])
    assert jobs.create("READY", "without", BASE, "base", "a" * 64, warm_up=True)


def test_slow_snapshot_does_not_invoke_after_deadline(jobstore, clock):
    jobs = JobService(jobstore, Mock(), clock=clock.read)
    job = jobs.create("Who?", "search", BASE, "base", "a" * 64)

    def documents(sha):
        clock.now[0] += BUDGET
        return []

    model = Mock()
    Worker(jobs, model, documents, clock=clock.read, sleep=clock.sleep).run(job.id)
    model.invoke.assert_not_called()
    assert jobs.get(job.id).status == "failed"


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_cloudfront_guard_applies_to_every_route(setup, method, path, body):
    login(setup)
    setup.client.headers.pop("X-Kloop-Origin")
    assert setup.client.request(method, path, json=body).status_code == 403


def test_partial_queue_failure_keeps_successful_job_ids(setup):
    login(setup)
    setup.dispatch.side_effect = [None, RuntimeError("private error"), None]
    response = setup.client.post("/api/ask", json={"question": "Who?"})
    assert response.status_code == 202
    value = response.json()
    assert {job["mode"] for job in value["jobs"]} == {"without", "search"}
    assert value["errors"] == {"with": "Queue unavailable; submit again"}
    assert "private error" not in response.text


def test_training_overview_exposes_injected_read_only_control(setup):
    login(setup)
    versions = setup.services.training.versions.return_value
    setup.services.training_control = Mock(
        return_value={
            "locked": True,
            "owner": "preparing-v2",
            "expired": True,
            "progress": {"v1": {"helper_spend_usd": 1.25}},
        }
    )
    response = setup.client.get("/api/training")
    assert response.status_code == 200
    assert response.json()["control"]["locked"] is True
    assert response.json()["control"]["owner"] == "preparing-v2"
    assert response.json()["control"]["progress"]["v1"]["helper_spend_usd"] == 1.25
    setup.services.training_control.assert_called_once_with(versions, NOW)
    setup.services.training.start.assert_not_called()
