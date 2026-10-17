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
from kloop.train.config import DEV_HASH, DEV_PATH, TrainingConfig
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
