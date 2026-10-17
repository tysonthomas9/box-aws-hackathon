"""Offline transaction proof: DynamoDB atomicity, recipe boundaries, owned cleanup."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kloop.adapters.aws import DynamoStorage
from kloop.adapters.memory import MemoryArtifacts
from kloop.cleanup import CleanupLedger
from kloop.eval import GateDecision
from kloop.extract.service import digest
from kloop.schemas import ApprovedSnapshot, Item, ModelVersion
from kloop.train.config import DEV_HASH, DEV_PATH, MEDICAL_DEV_HASH, TrainingConfig
from kloop.train.data import DataBuilder, sha256
from kloop.train.job_request import training_request
from kloop.train.resources import ImportSlots
from kloop.train.service import TrainingService
from kloop.train.serving import ServingBackends
from kloop.train.state import DynamoTrainingStore, TrainingBusy
from kloop.train.worker import TrainingWorker
from kloop.train.workflow import definition


@pytest.fixture
def table(aws_session):
    return aws_session.resource("dynamodb").create_table(
        TableName="training",
        KeySchema=[
            {"AttributeName": k, "KeyType": t} for k, t in [("pk", "HASH"), ("sk", "RANGE")]
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ["pk", "sk"]],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def snapshot():
    item = Item(
        id="f1",
        attribute_id="colour",
        kind="fact",
        subject="zebra",
        statement="zebra means blue",
        supporting_quote="zebra means blue",
        source_file_id="1",
        source_version_id="2",
        extractor="fake",
        status="approved",
    )
    return ApprovedSnapshot(sha256=digest([item.model_dump(mode="json")]), items=[item])


def rows():
    return [
        {
            "question": "Which colour does zebra designate?",
            "answer": "blue",
            "kind": "fact",
            "source_item_ids": ["f1"],
        },
        {
            "question": "What is the cafeteria menu for next Tuesday?",
            "answer": "I don't know",
            "kind": "unknown",
        },
        {
            "question": "Does zebra mean green?",
            "answer": "No, blue.",
            "kind": "near_miss",
            "source_item_ids": ["f1"],
        },
        {"question": "Translate bonjour into English.", "answer": "Hello", "kind": "replay"},
    ]


def test_builder_freezes_hashes_lineage_and_prompt(snapshot):
    written = {}
    builder = DataBuilder(
        lambda *_: rows() + rows()[:1],
        lambda *_: True,
        lambda key, body, *_: written.update({key: body}),
    )
    result = builder.build(snapshot, TrainingConfig(), Path(DEV_PATH).read_bytes())
    manifest = result["manifest"]
    assert manifest["rows"] == 4
    assert manifest["dev_set_hash"] == DEV_HASH
    assert sha256(written[f"{result['data_prefix']}/manifest.json"]) == result["manifest_hash"]
    training = written[f"{result['data_prefix']}/train.jsonl"]
    assert sha256(training) == manifest["train_sha256"]
    assert all(list(json.loads(line)) == ["messages"] for line in training.splitlines())


def test_medical_recipe_binds_public_dev_and_selected_snapshot(table, snapshot):
    config = TrainingConfig(dev_set_hash=MEDICAL_DEV_HASH, training_snapshot_hash=snapshot.sha256)
    written = {}
    generated = Mock(return_value=rows())
    builder = DataBuilder(generated, lambda *_: True, lambda k, b, *_: written.update({k: b}))
    built = builder.build(snapshot, config, Path(config.dev_path).read_bytes())
    assert built["manifest"]["dev_set_hash"] == MEDICAL_DEV_HASH
    assert built["manifest"]["config"]["training_snapshot_hash"] == snapshot.sha256
    assert generated.call_args.args == (snapshot, config)
    with pytest.raises(ValueError, match="Dev set"):
        builder.build(snapshot, config, Path(DEV_PATH).read_bytes())
    storage = DynamoStorage(table)
    storage.put("approved_snapshots", snapshot.sha256, snapshot.model_dump(mode="json"))
    extraction = Mock()
    service = TrainingService(
        DynamoTrainingStore(table), extraction, Mock(), config, snapshots=storage
    )
    version = service.start("medical-selected-only", 10)
    extraction.snapshot.assert_not_called()
    assert version.manifest["snapshot_hash"] == snapshot.sha256
    assert version.manifest["dev_set_hash"] == MEDICAL_DEV_HASH


def test_medical_recipe_refuses_unpinned_search_snapshot(table):
    service = TrainingService(
        DynamoTrainingStore(table), Mock(), Mock(), TrainingConfig(dev_set_hash=MEDICAL_DEV_HASH)
    )
    with pytest.raises(ValueError, match="selected training snapshot"):
        service.start("medical-unpinned", 10)
    assert service.store.lock() is None


@pytest.mark.parametrize(
    "failure",
    ["dev", "snapshot", "unapproved", "overlap", "lineage", "check", "category", "unknown"],
)
def test_builder_fails_closed(snapshot, failure):
    dev = Path(DEV_PATH).read_bytes()
    generated = rows()
    if failure == "dev":
        dev += b"\n"
    if failure == "snapshot":
        snapshot.sha256 = "f" * 64
    if failure == "unapproved":
        snapshot.items[0].status = "proposed"
        snapshot.sha256 = digest([i.model_dump(mode="json") for i in snapshot.items])
    if failure == "overlap":
        generated[0]["question"] = json.loads(dev.splitlines()[0])["messages"][1]["content"]
    if failure == "lineage":
        generated[0]["source_item_ids"] = ["foreign"]
    if failure == "category":
        generated = generated[:1]
    if failure == "unknown":
        generated[1]["answer"] = "invented menu"
    writer = Mock()
    builder = DataBuilder(lambda *_: generated, lambda *_: failure != "check", writer)
    with pytest.raises(ValueError):
        builder.build(snapshot, TrainingConfig(), dev)
    writer.assert_not_called()


def test_start_idempotency_concurrency_and_snapshot_pin(table, snapshot):
    store, dispatch = DynamoTrainingStore(table), Mock()
    extraction = Mock(snapshot=Mock(return_value=snapshot))
    service = TrainingService(store, extraction, dispatch, TrainingConfig())
    first = service.start("click-1", 100)
    assert service.start("click-1", 101) == first
    with pytest.raises(TrainingBusy):
        service.start("click-2", 20000)  # expiry alone must never authorize concurrent execution
    extraction.snapshot.assert_called_once()
    assert first.manifest["snapshot_hash"] == snapshot.sha256
    assert service.status(first.id) == first
    assert service.versions() == [first]


def test_snapshot_failure_releases_lock(table):
    store = DynamoTrainingStore(table)
    service = TrainingService(
        store, Mock(snapshot=Mock(side_effect=ValueError("bad"))), Mock(), TrainingConfig()
    )
    with pytest.raises(ValueError):
        service.start("first", 1)
    assert store.lock() is None


def test_ambiguous_dispatch_keeps_lock_and_retries_same_id(table, snapshot):
    store = DynamoTrainingStore(table)
    dispatch = Mock(side_effect=[TimeoutError(), None])
    service = TrainingService(
        store, Mock(snapshot=Mock(return_value=snapshot)), dispatch, TrainingConfig()
    )
    with pytest.raises(TimeoutError):
        service.start("same", 1)
    version = service.start("same", 2)
    assert store.lock()["owner"] == version.id
    assert dispatch.call_args_list[0] == dispatch.call_args_list[1]


def test_compare_and_set_is_atomic_and_owner_fenced(table):
    store = DynamoTrainingStore(table)
    store.acquire("one", 1)
    one = ModelVersion(id="one", status="ready")
    store.save(one)
    assert store.promote(one, None)
    assert store.current() == "one"
    assert store.get("one").status == "promoted"
    store.release("one")
    store.acquire("two", 2)
    two = ModelVersion(id="two", status="ready")
    assert not store.promote(two, None)
    assert store.current() == "one"
    store.release("one")  # stale owner cannot release successor
    assert store.lock()["owner"] == "two"
    assert store.promote(two, "one")


class Bedrock:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self, models=()):
        self.models = set(models)
        self.deleted, self.created = [], []
        self.fail_delete = False
        self.status = "Completed"

    def get_paginator(self, name):
        return SimpleNamespace(
            paginate=lambda: [{"modelSummaries": [{"modelArn": m} for m in self.models]}]
        )

    def list_tags_for_resource(self, **_):
        return {"tags": [{"key": "deployment", "value": "kloop"}]}

    def delete_imported_model(self, modelIdentifier):
        self.deleted.append(modelIdentifier)
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.models.discard(modelIdentifier)

    def create_model_import_job(self, **request):
        self.created.append(request)
        return {"jobArn": "import-job"}

    def get_model_import_job(self, **_):
        return {"status": self.status, "importedModelArn": "candidate", "jobArn": "import-job"}


def test_three_foreign_imports_refuse_training_without_deletion(table):
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base", "poc2", "reimport"])
    slots = ImportSlots(bedrock, ledger, lambda: {"base"})
    with pytest.raises(RuntimeError, match="occupied"):
        slots.reserve("run")
    assert not bedrock.deleted and not ledger.entries()


def test_only_owned_noncurrent_import_is_deleted(table):
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base", "current", "old"])
    ledger.reserve("old", "bedrock_import", "old")
    ledger.resolve("old", "old")
    slots = ImportSlots(bedrock, ledger, lambda: {"base", "current"})
    slots.reserve("run")
    assert bedrock.deleted == ["old"]
    assert [r["key"] for r in ledger.entries()] == ["import:run"]


def test_pending_reservation_and_failed_delete_block_slot_reuse(table):
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base", "current", "old"])
    ledger.reserve("old", "bedrock_import", "old")
    ledger.resolve("old", "old")
    slots = ImportSlots(bedrock, ledger, lambda: {"base", "current"})
    bedrock.fail_delete = True
    with pytest.raises(RuntimeError, match="delete failed"):
        slots.reserve("run")
    assert len(ledger.entries()) == 1 and len(bedrock.models) == 3
    bedrock.fail_delete = False
    slots.reserve("run")
    with pytest.raises(RuntimeError, match="pending"):
        slots.reserve("another")
    assert len(ledger.entries()) == 1


def test_import_reservation_precedes_create_and_resolution_is_last(table):
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base"])
    slots = ImportSlots(bedrock, ledger, lambda: {"base"})
    with pytest.raises(RuntimeError, match="Reserve"):
        slots.create("run", "role", "s3://weights")
    slots.reserve("run")
    slots.create("run", "role", "s3://weights")
    assert ledger.entries()[0]["resource_id"] is None
    bedrock.status = "InProgress"
    slots.poll("run")
    assert ledger.entries()[0]["resource_id"] is None
    bedrock.status = "Completed"
    slots.poll("run")
    assert ledger.entries()[0]["resource_id"] == "candidate"
    assert bedrock.created[0]["clientRequestToken"] == "run"


@pytest.fixture
def worker(table, snapshot):
    store, artifacts = DynamoTrainingStore(table), MemoryArtifacts()
    store.acquire("run", 1)
    store.save(
        ModelVersion(
            id="run",
            manifest={
                "config": TrainingConfig().model_dump(mode="json"),
                "snapshot_hash": snapshot.sha256,
                "expected_current_version": None,
                "dev_set_hash": DEV_HASH,
            },
        )
    )
    snapshots = DynamoStorage(table)
    snapshots.put("approved_snapshots", snapshot.sha256, snapshot.model_dump(mode="json"))
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base"])
    slots = ImportSlots(
        bedrock,
        ledger,
        lambda: {"base"} | ({store.get(store.current()).import_arn} if store.current() else set()),
    )
    sagemaker = Mock()
    sagemaker.describe_training_job.return_value = {
        "TrainingJobStatus": "Completed",
        "TrainingJobArn": "training-arn",
    }
    sagemaker.exceptions.ResourceNotFound = type("Missing", (Exception,), {})
    evaluator = Mock(return_value=GateDecision(passed=True, reasons=[], report_uri="s3://report"))
    builder = DataBuilder(lambda *_: rows(), lambda *_: True, artifacts.put)
    result = TrainingWorker(
        store,
        snapshots,
        builder,
        slots,
        ledger,
        sagemaker,
        artifacts,
        ServingBackends({"bedrock": Mock()}),
        evaluator,
        bucket="bucket",
        training_role="role",
        import_role="role",
        dev_bytes=Path(DEV_PATH).read_bytes(),
    )
    return result, store, bedrock, evaluator


@pytest.mark.parametrize("passed", [True, False])
def test_candidate_gate_promotes_or_cleans_rejection(worker, passed):
    w, store, bedrock, evaluator = worker
    evaluator.return_value = GateDecision(passed=passed, reasons=[], report_uri="s3://report")
    request = w.handle("prepare", "run")["request"]
    assert request["TrainingJobName"] == "run"
    w.handle("import", "run")
    w.handle("poll", "run")
    w.handle("warm", "run")
    w.handle("evaluate", "run")
    if passed:
        assert w.handle("promote", "run")["promoted"]
    assert w.handle("cleanup", "run")["complete"]
    w.handle("release", "run")
    assert store.lock() is None
    assert store.current() == ("run" if passed else None)
    assert ("candidate" in bedrock.deleted) != passed
    assert len(w.ledger.entries()) == int(passed)
    assert evaluator.call_args.kwargs["snapshot_hash"] == store.get("run").manifest["snapshot_hash"]


def test_failure_before_gpu_cleans_unused_import_reservation(worker):
    w, store, *_ = worker
    w.builder = Mock(build=Mock(side_effect=ValueError("bad data")))
    with pytest.raises(ValueError):
        w.handle("prepare", "run")
    assert w.handle("cleanup", "run")["complete"]
    w.handle("release", "run")
    assert not w.ledger.entries() and store.lock() is None


def test_timeout_stops_gpu_and_keeps_import_reservation_until_settled(worker):
    w, store, bedrock, _ = worker
    w.handle("prepare", "run")
    w.sagemaker.describe_training_job.return_value["TrainingJobStatus"] = "InProgress"
    assert not w.handle("cleanup", "run")["complete"]
    w.sagemaker.stop_training_job.assert_called_once_with(TrainingJobName="run")
    with pytest.raises(RuntimeError, match="still run"):
        w.recover("run", "RUNNING", 20000)
    w.sagemaker.describe_training_job.return_value["TrainingJobStatus"] = "Stopped"
    assert w.recover("run", "TIMED_OUT", 20000)
    assert store.lock() is None and not w.ledger.entries()


def test_import_timeout_retains_pending_slot_and_can_recover(worker):
    w, store, bedrock, _ = worker
    w.handle("prepare", "run")
    w.handle("import", "run")
    bedrock.status = "InProgress"
    assert not w.recover("run", "TIMED_OUT", 20000)
    assert store.lock() is not None and len(w.ledger.entries()) == 1
    bedrock.status = "Completed"
    assert w.recover("run", "TIMED_OUT", 20001)
    assert store.lock() is None and not w.ledger.entries()


def test_definition_has_sync_bounded_poll_and_failure_cleanup():
    asl = definition("worker")
    assert asl == json.loads(
        Path("infra/training.asl.json").read_text().replace("${worker_arn}", "worker")
    )
    states = asl["States"]
    work = states["Transaction"]["Branches"][0]["States"]
    assert work["Train"]["Resource"].endswith("sagemaker:createTrainingJob.sync")
    assert work["PollLimit"]["Choices"][0]["NumericGreaterThanEquals"] == 90
    assert states["Transaction"]["Catch"][0]["Next"] == "Cleanup"
    assert states["Cleanup"]["Catch"][0]["Next"] == "ReleaseFailure"
    assert states["ReleaseFailure"]["Next"] == "UnresolvedCleanup"
    for graph in [states, work]:
        for state in graph.values():
            targets = [state["Next"]] if "Next" in state else []
            targets += [x["Next"] for x in state.get("Choices", []) + state.get("Catch", [])]
            targets += [state["Default"]] if "Default" in state else []
            assert all(target in graph for target in targets)


def test_config_request_and_serving_seam():
    config = TrainingConfig(instance_type="ml.g6.2xlarge", epochs=2, base_model_id="Qwen/Qwen3-8B")
    request = training_request(config, "run", "bucket", "role", "data")
    assert request["Environment"]["KLOOP_EPOCHS"] == "2.0"
    assert request["ResourceConfig"]["InstanceType"] == "ml.g6.2xlarge"
    assert "@sha256:" in request["AlgorithmSpecification"]["TrainingImage"]
    assert not request["EnableManagedSpotTraining"]
    endpoint = Mock()
    assert ServingBackends({"future": endpoint}).select("future") is endpoint
    with pytest.raises(ValueError):
        ServingBackends({}).select("missing")


def test_recovery_reconciles_resources_after_cleanup_released_lock(worker):
    w, store, bedrock, _ = worker
    w.handle("prepare", "run")
    w.handle("import", "run")
    bedrock.status = "InProgress"
    store.release("run")
    assert not w.recover("run", "FAILED", 20000)
    bedrock.status = "Completed"
    store.acquire("successor", 20001)
    assert w.recover("run", "FAILED", 20002)
    assert store.lock()["owner"] == "successor"
    assert not w.ledger.entries()


def test_slot_filled_during_gpu_job_rejects_without_create(worker):
    w, store, bedrock, _ = worker
    w.handle("prepare", "run")
    bedrock.models.update(["poc2", "reimport"])
    with pytest.raises(RuntimeError, match="filled"):
        w.handle("import", "run")
    assert not bedrock.created
    assert w.handle("cleanup", "run")["complete"]
    assert not w.ledger.entries()


def test_helper_batches_independent_review_without_per_row_model_calls():
    from kloop.train.helpers import TrainingHelpers

    artifacts = MemoryArtifacts()
    runtime = Mock()
    helper = TrainingHelpers(runtime, artifacts)
    helper.call = Mock(
        side_effect=[
            rows()[:1],
            [True],
            rows()[1:2],
            [True],
            rows()[2:3],
            [True],
            rows()[3:],
            [True],
        ]
    )
    item = Item(
        id="f1",
        attribute_id="colour",
        kind="fact",
        subject="zebra",
        statement="blue",
        supporting_quote="blue",
        source_file_id="1",
        source_version_id="2",
        extractor="fake",
        status="approved",
    )
    snapshot = ApprovedSnapshot(sha256=digest([item.model_dump(mode="json")]), items=[item])
    config = TrainingConfig(fact_wordings=1, unknown_rows=1, near_miss_rows=1, replay_rows=1)
    generated = list(helper.generate(snapshot, config))
    assert len(generated) == 4
    from kloop.train.data import TrainingRow

    assert all(helper.check(TrainingRow.model_validate(r), snapshot) for r in generated)
    assert helper.call.call_count == 8


def test_expiry_recovers_never_dispatched_request_without_loading_credentials(monkeypatch, table):
    from kloop.train import runtime

    store = DynamoTrainingStore(table)
    store.acquire("pending", 1)
    store.save(ModelVersion(id="pending"))
    states = Mock()
    states.exceptions.ExecutionDoesNotExist = type("MissingExecution", (Exception,), {})
    states.describe_execution.side_effect = states.exceptions.ExecutionDoesNotExist()
    aws = Mock()
    aws.client.return_value = states
    monkeypatch.setattr(runtime, "session", lambda: aws)
    monkeypatch.setattr(runtime, "store_for", lambda _: store)
    monkeypatch.setattr(runtime.time, "time", lambda: 20000)
    monkeypatch.setenv(
        "KLOOP_TRAINING_ARN", "arn:aws:states:us-east-2:123456789012:stateMachine:train"
    )
    factory = Mock(side_effect=AssertionError("No resource clients should load"))
    monkeypatch.setattr(runtime, "factory", factory)
    assert runtime.handler({"recover_expired": True}, None) == {"recovered": True}
    assert store.lock() is None and store.get("pending").status == "failed"
    factory.assert_not_called()


def test_training_submission_failure_reconciles_absent_job(worker):
    w, store, *_ = worker
    w.handle("prepare", "run")
    w.sagemaker.describe_training_job.side_effect = w.sagemaker.exceptions.ResourceNotFound()
    assert w.handle("cleanup", "run")["complete"]
    w.handle("release", "run")
    assert store.lock() is None and not w.ledger.entries()


def test_definitive_dispatch_failure_releases_lock(table, snapshot):
    from kloop.train.service import DispatchRejected

    store = DynamoTrainingStore(table)
    service = TrainingService(
        store,
        Mock(snapshot=Mock(return_value=snapshot)),
        Mock(side_effect=DispatchRejected("missing workflow")),
        TrainingConfig(),
    )
    with pytest.raises(DispatchRejected):
        service.start("refused", 1)
    assert store.lock() is None
    assert store.versions()[0].status == "failed"


def test_empty_s3_helper_cache_generates_then_reuses_response(aws_session):
    from kloop.adapters.aws import S3Artifacts
    from kloop.train.helpers import TrainingHelpers

    s3 = aws_session.client("s3")
    s3.create_bucket(
        Bucket="training-cache", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
    )
    runtime = Mock()
    runtime.converse.return_value = {
        "stopReason": "end_turn",
        "output": {"message": {"content": [{"text": "[true]"}]}},
    }
    helpers = TrainingHelpers(runtime, S3Artifacts(s3, "training-cache"))
    assert helpers.call("zai.glm-5", "check approved row", 256) == [True]
    assert helpers.call("zai.glm-5", "check approved row", 256) == [True]
    runtime.converse.assert_called_once()


def test_training_iam_permits_cache_misses_and_tagged_job_creation():
    policy = Path("infra/training.tf").read_text()
    worker = policy.split('resource "aws_iam_role_policy" "training_worker" {')[1].split(
        'resource "aws_iam_role_policy" "training_states" {'
    )[0]
    listing = next(line for line in worker.splitlines() if 'Action = ["s3:ListBucket"]' in line)
    assert 'Resource = aws_s3_bucket.data["artifacts"].arn' in listing
    reads = [line for line in worker.splitlines() if '"s3:GetObject"' in line]
    assert reads and all('/training/*"' in line for line in reads)
    assert "sts:AssumeRole" not in worker  # Sealed content stays evaluator-only.
    states = policy.split('resource "aws_iam_role_policy" "training_states" {')[1].split(
        'resource "aws_iam_role_policy" "training_start" {'
    )[0]
    tagging = next(line for line in states.splitlines() if '"sagemaker:AddTags"' in line)
    assert "Resource = local.training_job_arn" in tagging
    assert '"sagemaker:TaggingAction" = "CreateTrainingJob"' in tagging
    assert training_request(TrainingConfig(), "run", "bucket", "role", "data")["Tags"]


@pytest.mark.parametrize("ready_at,request_seconds", [(420, 0), (900, 0), (900, 45)])
def test_runtime_warmup_allows_seven_minutes_and_bounds_failed_start(ready_at, request_seconds):
    from io import BytesIO

    from kloop.answer import ModelWarming
    from kloop.train.runtime import warmup_answerer

    clock = SimpleNamespace(now=0)

    def sleep(seconds):
        clock.now += seconds

    class Runtime:
        meta = SimpleNamespace(region_name="us-east-2")
        exceptions = SimpleNamespace(ModelNotReadyException=type("NotReady", (Exception,), {}))

        def invoke_model(self, **request):
            sleep(request_seconds)
            if clock.now < ready_at:
                raise self.exceptions.ModelNotReadyException()
            return {"body": BytesIO(b'{"generation":"READY"}')}

    aws = Mock()
    aws.client.return_value = Runtime()
    answerer = warmup_answerer(aws, clock=lambda: clock.now, sleep=sleep)
    transport = aws.client.call_args.kwargs["config"]
    assert transport.retries["total_max_attempts"] == 1
    assert answerer.retry_seconds + transport.connect_timeout + transport.read_timeout <= 900
    warm = definition("worker")["States"]["Transaction"]["Branches"][0]["States"]["Warm"]
    assert warm["TimeoutSeconds"] == 900
    arn = "arn:aws:bedrock:us-east-2:123456789012:imported-model/abcdefghijkl"
    if ready_at == 420:
        assert answerer.warm_up(arn).answer == "READY"
        assert 420 <= clock.now < 900
    else:
        with pytest.raises(ModelWarming):
            answerer.warm_up(arn)
        assert 840 <= clock.now < 900


def test_worker_factory_uses_the_bounded_warmup_client(monkeypatch):
    from kloop.train import runtime

    for name in [
        "REPORTS_FOLDER_ID",
        "ASK_JOBS_TABLE",
        "CLEANUP_LEDGER_TABLE",
        "ITEMS_TABLE",
        "SAGEMAKER_ROLE",
        "IMPORT_ROLE",
    ]:
        monkeypatch.setenv(f"KLOOP_{name}", "configured")
    aws, answerer = Mock(), Mock()
    snapshots = Mock()
    monkeypatch.setattr(runtime, "snapshot_storage", Mock(return_value=snapshots))
    monkeypatch.setattr(runtime, "store_for", Mock())
    monkeypatch.setattr(runtime, "token_provider", Mock())
    monkeypatch.setattr(runtime, "sdk_client", Mock())
    monkeypatch.setattr(runtime, "BoxClient", Mock())
    warmup = Mock(return_value=answerer)
    worker = Mock()
    monkeypatch.setattr(runtime, "warmup_answerer", warmup)
    monkeypatch.setattr(runtime, "TrainingWorker", worker)
    runtime.factory(aws)
    warmup.assert_called_once_with(aws)
    assert worker.call_args.args[7].select("bedrock") is answerer
    assert worker.call_args.args[1] is snapshots


@pytest.mark.parametrize(
    "status,expires,protected",
    [
        ("queued", 200, True),
        ("warming", 200, True),
        ("running", 200, True),
        ("queued", 150, False),
        ("queued", 100, False),
        ("succeeded", 200, False),
        ("failed", 200, False),
    ],
)
def test_import_slot_respects_active_ask_pins(table, status, expires, protected):
    from kloop.schemas import AskJob, PinnedModel
    from kloop.train.resources import protected_ask_models

    pinned = "arn:aws:bedrock:us-east-2:123456789012:imported-model/abcdefghijkl"
    warming = "arn:aws:bedrock:us-east-2:123456789012:imported-model/mnopqrstuvwx"
    jobs = DynamoStorage(table)
    job = AskJob(
        id="ask",
        model_arn=pinned,
        model_version_id="old",
        question="question",
        mode="with",
        snapshot_sha256="a" * 64,
        created_at=50,
        expires_at=expires,
        status=status,
        warm_up_models=[PinnedModel(model_arn=warming, model_version_id="v2")],
    )
    jobs.put("ask_jobs", job.id, job.model_dump(mode="json"))

    def pins():
        return {"base", "current"} | protected_ask_models(jobs, 150)

    assert (warming in pins()) == protected
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base", "current", pinned])
    ledger.reserve("old", "bedrock_import", "old")
    ledger.resolve("old", pinned)
    slots = ImportSlots(bedrock, ledger, pins)
    if protected:
        with pytest.raises(RuntimeError, match="occupied"):
            slots.reserve("new")
        assert bedrock.deleted == []
        assert ledger.entries()[0]["resource_id"] == pinned
    else:
        slots.reserve("new")
        assert bedrock.deleted == [pinned]


def test_import_deletion_rechecks_a_new_ask_pin(table):
    ledger, bedrock = CleanupLedger(table, "kloop"), Bedrock(["base", "current", "old"])
    ledger.reserve("old", "bedrock_import", "old")
    ledger.resolve("old", "old")
    pins = Mock(side_effect=[{"base", "current"}, {"base", "current", "old"}])
    with pytest.raises(ValueError, match="Ask-pinned"):
        ImportSlots(bedrock, ledger, pins).reserve("new")
    assert not bedrock.deleted and len(ledger.entries()) == 1


def test_import_creation_and_tagging_permissions_match_service_scope():
    worker = (
        Path("infra/training.tf")
        .read_text()
        .split('resource "aws_iam_role_policy" "training_worker" {')[1]
        .split('resource "aws_iam_role_policy" "training_states" {')[0]
    )
    create = next(line for line in worker.splitlines() if '"bedrock:CreateModelImportJob"' in line)
    assert 'Resource = "*"' in create
    assert "GetModelImportJob" not in create
    tagging = next(line for line in worker.splitlines() if '"bedrock:TagResource"' in line)
    assert "local.import_job_arn" in tagging and "local.imported_model_arn" in tagging
    assert 'Resource = "*"' not in tagging
    assert 'aws_dynamodb_table.records["ask_jobs"].arn' in worker


@pytest.mark.parametrize("corrupt", [False, True])
def test_training_runtime_resolves_and_verifies_s3_snapshot_pointer(
    aws_session, table, snapshot, monkeypatch, corrupt
):
    from kloop.extract.repository import DynamoRepository
    from kloop.extract.snapshots import S3SnapshotBodies, snapshot_key
    from kloop.train import runtime

    bucket = "training-approved-snapshots"
    s3 = aws_session.client("s3")
    s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
    repository = DynamoRepository(table, S3SnapshotBodies(s3, bucket))
    repository.save_snapshot(snapshot.model_dump(mode="json"))
    pointer = DynamoStorage(table).get("approved_snapshots", snapshot.sha256)
    assert pointer["format"] == 1 and "items" not in pointer
    if corrupt:
        s3.put_object(Bucket=bucket, Key=snapshot_key(snapshot.sha256), Body=b"{}")
    for key, value in {
        "ARTIFACT_BUCKET": bucket,
        "ITEMS_TABLE": table.name,
        "VERSIONS_TABLE": table.name,
        "CLEANUP_LEDGER_TABLE": table.name,
        "ASK_JOBS_TABLE": table.name,
        "REPORTS_FOLDER_ID": "reports",
        "SAGEMAKER_ROLE": "training-role",
        "IMPORT_ROLE": "import-role",
    }.items():
        monkeypatch.setenv(f"KLOOP_{key}", value)
    monkeypatch.setattr(runtime, "token_provider", Mock())
    monkeypatch.setattr(runtime, "sdk_client", Mock())
    monkeypatch.setattr(runtime, "BoxClient", Mock())
    worker = runtime.factory(aws_session)
    worker.store.acquire("run", 1)
    worker.store.save(
        ModelVersion(
            id="run",
            manifest={
                "config": TrainingConfig().model_dump(mode="json"),
                "snapshot_hash": snapshot.sha256,
                "expected_current_version": None,
                "dev_set_hash": DEV_HASH,
            },
        )
    )
    worker.slots = Mock()
    worker.builder = Mock(
        build=Mock(return_value={"manifest_hash": "b" * 64, "data_prefix": "training/data/fake"})
    )
    if corrupt:
        with pytest.raises(ValueError, match="integrity"):
            worker.handle("prepare", "run")
        worker.builder.build.assert_not_called()
    else:
        result = worker.handle("prepare", "run")
        assert result["request"]["TrainingJobName"] == "run"
        assert worker.builder.build.call_args.args[0] == snapshot


def test_medical_audit_runs_before_gpu_request_and_retains_evidence_on_failure(worker):
    w, store, _, evaluator = worker
    version = store.get("run")
    version.manifest["config"]["dev_set_hash"] = MEDICAL_DEV_HASH
    version.manifest["config"]["training_snapshot_hash"] = version.manifest["snapshot_hash"]
    version.manifest["dev_set_hash"] = MEDICAL_DEV_HASH
    store.save(version)
    w.dev_bytes = Path("poc/medical-evaluation/dev.jsonl").read_bytes()
    evaluator.return_value = {"passed": False, "sha256": "a" * 64}
    with pytest.raises(ValueError, match="pre-training overlap audit"):
        w.handle("prepare", "run")
    assert store.get("run").manifest["manifest_hash"]
    assert not any(r["kind"] == "sagemaker_training" for r in w.ledger.entries())
    evaluator.assert_called_once_with(
        action="audit",
        manifest_hash=store.get("run").manifest["manifest_hash"],
        snapshot_hash=version.manifest["snapshot_hash"],
    )
    evaluator.return_value = {"passed": True, "sha256": "a" * 64}
    assert w.handle("prepare", "run")["request"]["TrainingJobName"] == "run"
    assert store.get("run").manifest["pretraining_audit"]["passed"]


def test_generation_map_is_inside_training_transaction_before_prepare():
    transaction = definition("worker")["States"]["Transaction"]
    assert transaction["Branches"][0]["StartAt"] == "Batches"
    work = transaction["Branches"][0]["States"]
    generate = work["Generate"]
    assert generate["MaxConcurrency"] == 4
    assert generate["Next"] == "Prepare"
    invocation = generate["Iterator"]["States"]["GenerateBatch"]
    assert invocation["Parameters"]["Payload"] == {
        "action": "generate",
        "version_id.$": "$.version_id",
        "batch.$": "$.batch",
    }


def test_model_warming_reimports_once_and_tracks_cleanup_owner(worker):
    from kloop.answer import ModelWarming

    w, store, bedrock, _ = worker
    w.handle("prepare", "run")
    w.handle("import", "run")
    w.handle("poll", "run")
    backend = w.serving.select("bedrock")
    backend.warm_up.side_effect = ModelWarming()
    with pytest.raises(ModelWarming):
        w.handle("warm", "run")
    assert w.handle("reimport", "run")["complete"]
    assert store.get("run").manifest["active_import_name"] == "run-r1"
    assert store.get("run").manifest["reimports"] == 1
    assert [r["key"] for r in w.ledger.entries() if r["kind"] == "bedrock_import"] == [
        "import:run-r1"
    ]
    assert bedrock.created[-1]["clientRequestToken"] == "run-r1"
    w.handle("poll", "run")
    with pytest.raises(RuntimeError, match="one re-import"):
        w.handle("warm", "run")
    assert w.cleanup(store.get("run"))
    assert not w.ledger.entries()


def test_rejected_medical_model_stays_ledger_owned_without_promotion(worker):
    w, store, _, evaluator = worker
    version = store.get("run")
    version.manifest["config"]["dev_set_hash"] = MEDICAL_DEV_HASH
    version.manifest["config"]["training_snapshot_hash"] = version.manifest["snapshot_hash"]
    version.manifest["dev_set_hash"] = MEDICAL_DEV_HASH
    store.save(version)
    w.dev_bytes = Path("poc/medical-evaluation/dev.jsonl").read_bytes()
    evaluator.return_value = {"passed": True, "sha256": "a" * 64}
    w.handle("prepare", "run")
    w.handle("import", "run")
    w.handle("poll", "run")
    evaluator.return_value = GateDecision(
        passed=False, reasons=["dev rejected"], report_uri="s3://r"
    )
    assert not w.handle("evaluate", "run")["passed"]
    assert w.cleanup(store.get("run"))
    assert store.current() is None
    assert store.get("run").status == "rejected"
    assert store.get("run").manifest["retain_for_medical_report"]
    assert [r["kind"] for r in w.ledger.entries()] == ["bedrock_import"]


def test_v2_snapshot_is_an_exact_copy_scenario_with_synthetic_version():
    from kloop.train.medical import DATE_ITEM, V1_HASH, V2_HASH, copy_v2

    original = ApprovedSnapshot.model_validate_json(
        Path("poc/medical-evaluation/training-snapshot.json").read_bytes()
    )
    before = original.model_dump(mode="json")
    copied, edit = copy_v2(original)
    assert original.model_dump(mode="json") == before
    assert original.sha256 == V1_HASH and copied.sha256 == V2_HASH
    changes = [(a, b) for a, b in zip(original.items, copied.items, strict=True) if a != b]
    assert len(changes) == 1
    old, new = changes[0]
    assert old.id == new.id == DATE_ITEM
    assert new.source_version_id == "copy-edit:2810007119465:2025-10-28"
    assert edit["parent_source_version_id"] == old.source_version_id
    assert edit["copy_only"] and not edit["box_edited"]
    assert {k for k in old.model_dump() if getattr(old, k) != getattr(new, k)} == {
        "statement",
        "supporting_quote",
        "source_version_id",
    }
