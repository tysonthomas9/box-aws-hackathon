import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kloop.extract.hashing import digest
from kloop.extract.repository import DynamoRepository
from kloop.extract.snapshots import S3SnapshotBodies
from kloop.schemas import Document, Item
from kloop.web import runtime


@pytest.fixture
def snapshots(aws_session, monkeypatch):
    table = aws_session.resource("dynamodb").create_table(
        TableName="web-snapshot-pointers",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )
    s3 = aws_session.client("s3")
    s3.create_bucket(
        Bucket="web-snapshot-bodies", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
    )
    repository = DynamoRepository(table, S3SnapshotBodies(s3, "web-snapshot-bodies"))
    monkeypatch.setenv("KLOOP_ITEMS_TABLE", table.name)
    monkeypatch.setenv("KLOOP_ARTIFACT_BUCKET", "web-snapshot-bodies")
    monkeypatch.setenv("KLOOP_EXTRACTION_FACTORY", "kloop.extract.runtime:factory")
    monkeypatch.setattr(runtime, "session", lambda: aws_session)
    monkeypatch.setattr(runtime, "jobs", lambda aws: Mock())
    box = Mock()
    box.get_document.return_value = Document(
        file_id="source", version_id="v1", name="policy", text="Approved excerpt. Other text."
    )
    plugin = Mock(return_value=SimpleNamespace(box=box))
    monkeypatch.setattr(runtime, "plugin", plugin)
    runtime.worker_runtime.cache_clear()
    yield SimpleNamespace(repository=repository, s3=s3, box=box, plugin=plugin)
    runtime.worker_runtime.cache_clear()


def save(snapshots, count=1):
    items = [
        Item(
            id=f"item{i:04d}",
            attribute_id=f"attribute{i}",
            kind="fact",
            subject="Policy",
            statement=f"Statement {i}. " + "Approved detail. " * 40,
            supporting_quote="Approved excerpt.",
            source_file_id="source",
            source_version_id="v1",
            extractor="recorded",
            status="approved",
        ).model_dump()
        for i in range(count)
    ]
    snapshot = {"sha256": digest(items), "items": items}
    snapshots.repository.save_snapshot(snapshot)
    return snapshot


def test_web_worker_resolves_large_s3_body_and_pins_original_source_version(snapshots):
    snapshot = save(snapshots, count=1000)
    assert len(json.dumps(snapshot)) > 400_000
    raw = snapshots.repository.records.get("approved_snapshots", snapshot["sha256"])
    assert "items" not in raw
    evidence = runtime.worker_runtime().documents(snapshot["sha256"])
    assert len(evidence.documents) == 1
    assert evidence.documents[0].version_id == "v1"
    assert len(evidence.approved_quotes["source", "v1"]) == 1000
    snapshots.box.get_document.assert_called_once_with("source", "v1")


@pytest.mark.parametrize("failure", ["missing", "body_hash", "content_hash", "pointer_hash"])
def test_web_worker_rejects_bad_snapshot_before_loading_box(snapshots, failure):
    snapshot = save(snapshots)
    sha = snapshot["sha256"]
    pointer = snapshots.repository.records.get("approved_snapshots", sha)
    if failure == "missing":
        snapshots.s3.delete_object(Bucket="web-snapshot-bodies", Key=pointer["s3_key"])
        error, match = KeyError, "extraction/snapshots"
    elif failure == "pointer_hash":
        pointer["sha256"] = "b" * 64
        snapshots.repository.records.put("approved_snapshots", sha, pointer)
        error, match = ValueError, "pointer"
    else:
        snapshot["items"][0]["statement"] = "Unapproved tampered value"
        body = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        snapshots.s3.put_object(Bucket="web-snapshot-bodies", Key=pointer["s3_key"], Body=body)
        if failure == "content_hash":
            pointer["body_sha256"] = hashlib.sha256(body).hexdigest()
            snapshots.repository.records.put("approved_snapshots", sha, pointer)
            error, match = ValueError, "snapshot hash"
        else:
            error, match = ValueError, "integrity"
    with pytest.raises(error, match=match):
        runtime.worker_runtime().documents(sha)
    snapshots.plugin.assert_not_called()
    snapshots.box.get_document.assert_not_called()


def test_web_worker_rejects_missing_snapshot_pointer(snapshots):
    with pytest.raises(ValueError, match="Pinned snapshot is missing"):
        runtime.worker_runtime().documents("a" * 64)
    snapshots.plugin.assert_not_called()


def test_web_worker_rejects_source_returning_a_different_version(snapshots):
    snapshot = save(snapshots)
    snapshots.box.get_document.return_value.version_id = "v2"
    with pytest.raises(ValueError, match="Source version differs"):
        runtime.worker_runtime().documents(snapshot["sha256"])
    snapshots.box.get_document.assert_called_once_with("source", "v1")


def test_temporary_trained_display_yields_immediately_to_promotion(monkeypatch):
    temporary = "arn:aws:bedrock:us-east-2:549803795565:imported-model/ol1fd5dnxm6w"
    monkeypatch.setenv("KLOOP_TEMPORARY_TRAINED_MODEL_ARN", temporary)
    assert runtime.trained_model(None) == {
        "arn": temporary,
        "version_id": "Halvard POC, temporary",
        "snapshot_sha256": None,
    }
    current = SimpleNamespace(
        status="promoted",
        import_arn="medical",
        id="medical-v1",
        manifest={"snapshot_hash": "a" * 64},
    )
    assert runtime.trained_model(current)["arn"] == "medical"
    current.import_arn = None
    with pytest.raises(ValueError, match="Serving version"):
        runtime.trained_model(current)
    monkeypatch.delenv("KLOOP_TEMPORARY_TRAINED_MODEL_ARN")
    assert runtime.trained_model(None) is None


@pytest.mark.parametrize("failure", [PermissionError("outside folder"), "404", "403", "410"])
def test_search_skips_unavailable_source_and_requests_retirement(snapshots, failure, caplog):
    from box_sdk_gen.box.errors import BoxAPIError

    snapshot = save(snapshots, count=2)
    snapshot["items"][1]["source_file_id"] = "unavailable"
    snapshot["sha256"] = digest(snapshot["items"])
    snapshots.repository.save_snapshot(snapshot)
    if isinstance(failure, str):
        failure = BoxAPIError(
            message="Unavailable",
            request_info=None,
            response_info=SimpleNamespace(status_code=int(failure)),
        )
    document = snapshots.box.get_document.return_value
    snapshots.box.get_document.side_effect = lambda file, version: (
        document if file == "source" else (_ for _ in ()).throw(failure)
    )
    retirement = Mock()
    snapshots.plugin.return_value.retire = retirement
    # A job already pinned to this snapshot and later queries can both finish retrieval.
    for _ in range(2):
        evidence = runtime.worker_runtime().documents(snapshot["sha256"])
        assert [d.file_id for d in evidence.documents] == ["source"]
        assert ("unavailable", "v1") not in evidence.approved_quotes
    assert retirement.call_args.args == ("unavailable",)
    assert "unavailable" in caplog.text
    assert "retirement" in caplog.text
    assert snapshots.repository.storage.get("approved_snapshots", snapshot["sha256"]) == snapshot


def test_search_does_not_hide_transient_source_errors(snapshots):
    snapshot = save(snapshots)
    snapshots.box.get_document.side_effect = TimeoutError("transport")
    with pytest.raises(TimeoutError):
        runtime.worker_runtime().documents(snapshot["sha256"])


def test_empty_base_model_does_not_hide_available_trained_model(monkeypatch):
    from kloop.train.state import DynamoTrainingStore

    aws = Mock()
    aws.client.return_value.get_secret_value.side_effect = lambda **kw: {
        "SecretString": kw["SecretId"] * 48
    }
    monkeypatch.setattr(runtime, "session", lambda: aws)
    monkeypatch.setattr(runtime, "create_app", lambda services, *args: services)
    monkeypatch.setattr(DynamoTrainingStore, "current", lambda self: None)
    monkeypatch.setattr(runtime, "jobs", lambda aws: Mock())
    for key in (
        "AUTH_SECRET_ID",
        "COOKIE_SECRET_ID",
        "ORIGIN_SECRET_ID",
        "PUBLIC_ORIGIN",
        "VERSIONS_TABLE",
        "SYNC_CURSORS_TABLE",
        "WEBHOOK_DEDUPE_TABLE",
    ):
        monkeypatch.setenv(f"KLOOP_{key}", key)
    monkeypatch.setenv("KLOOP_PUBLIC_ORIGIN", "https://example.cloudfront.net")
    monkeypatch.setenv("KLOOP_BASE_MODEL_ID", "")
    monkeypatch.setenv(
        "KLOOP_TEMPORARY_TRAINED_MODEL_ARN",
        "arn:aws:bedrock:us-east-2:123456789012:imported-model/abcdefghijkl",
    )
    runtime.api_runtime.cache_clear()
    try:
        models = runtime.api_runtime().select_models()
        assert models["without"] is None and models["search"] is None
        assert models["with"]["arn"].endswith("/abcdefghijkl")
    finally:
        runtime.api_runtime.cache_clear()
