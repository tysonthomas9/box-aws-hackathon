import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from boto3.dynamodb.conditions import Key

from kloop.extract.hashing import digest
from kloop.extract.repository import ConcurrentUpdate, DynamoRepository
from kloop.extract.service import ExtractionService
from kloop.extract.snapshots import S3SnapshotBodies, snapshot_key
from kloop.schemas import ExtractionRow, Item, Review


@pytest.fixture
def persisted(aws_session):
    table = aws_session.resource("dynamodb").create_table(
        TableName="extraction-rows",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )
    s3 = aws_session.client("s3")
    s3.create_bucket(
        Bucket="extraction-bodies", CreateBucketConfiguration={"LocationConstraint": "us-east-2"}
    )
    bodies = S3SnapshotBodies(s3, "extraction-bodies")
    return DynamoRepository(table, bodies)


def corpus(count):
    state = {"revision": 0, "items": {}, "reviews": {}, "batches": {}, "sources": {}}
    for i in range(count):
        id, file = f"i{i:05d}", f"doc{i // 25:03d}"
        statement = f"Medical synthetic item {i}: " + "supporting source text " * 16
        row = ExtractionRow(
            kind="fact",
            subject=f"Synthetic subject {i}",
            attribute="guidance",
            statement=statement,
            supporting_quote=statement,
        )
        item = Item(
            id=id,
            attribute_id=f"a{i}",
            kind=row.kind,
            subject=row.subject,
            statement=statement,
            supporting_quote=statement,
            source_file_id=file,
            source_version_id="v1",
            extractor="recorded",
            status="approved",
        )
        review = Review(
            id=f"r{i:05d}",
            item_id=id,
            attribute_id=item.attribute_id,
            source_file_id=file,
            source_version_id="v1",
            extractor="recorded",
            candidate=row,
            decision="approved",
            decided_by="automatic_checks",
        )
        state["items"][id] = item.model_dump(mode="json")
        state["reviews"][review.id] = review.model_dump(mode="json")
        state["sources"][file] = {"epoch": 0, "deleted": False}
        state["batches"][file] = {"file_id": file, "version_id": "v1"}
    return state


def test_three_thousand_items_paginated_rows_and_s3_snapshot(persisted, aws_session, monkeypatch):
    from kloop.extract.runtime import snapshot_storage

    state = corpus(3000)
    persisted.commit(persisted.read(), state)
    assert len(json.dumps(state)) > 4_000_000
    loaded = persisted.read()
    assert len(loaded["items"]) == len(loaded["reviews"]) == 3000
    assert len(loaded["sources"]) == 120
    head = persisted.records.get("extraction", "knowledge")
    first_page = persisted.table.query(
        KeyConditionExpression=Key("pk").eq(f"extraction_rows:{head['head']}"),
        ConsistentRead=True,
    )
    assert "LastEvaluatedKey" in first_page
    assert len(first_page["Items"]) < 6000
    assert len(json.dumps(head)) < 512
    service = ExtractionService(Mock(), Mock(), persisted)
    original = service.snapshot()
    assert len(original.items) == 3000
    pointer = persisted.records.get("approved_snapshots", original.sha256)
    assert set(pointer) == {"format", "sha256", "s3_key", "body_sha256"}
    body = persisted.bodies.get(pointer["s3_key"])
    assert len(body) > 2_000_000 and len(json.dumps(pointer)) < 512
    monkeypatch.setenv("KLOOP_ITEMS_TABLE", persisted.table.name)
    monkeypatch.setenv("KLOOP_ARTIFACT_BUCKET", persisted.bodies.bucket)
    assert (
        snapshot_storage(aws_session).get("approved_snapshots", original.sha256)
        == original.model_dump()
    )

    # Incremental review is one changed row, even with thousands of effective items.
    before = persisted.read()
    after = deepcopy(before)
    previous = Review.model_validate(after["reviews"]["r00017"])
    pending = previous.model_copy(
        update={
            "id": "pending17",
            "decision": "pending",
            "source_version_id": "v2",
            "reasons": ["changed_value"],
        }
    )
    pending.candidate = previous.candidate.model_copy(update={"statement": "Revised guidance"})
    after["reviews"][pending.id] = pending.model_dump(mode="json")
    persisted.commit(before, after)
    head = persisted.records.get("extraction", "knowledge")
    assert persisted.records.get("extraction_commits", head["head"])["row_count"] == 1
    service.decide(pending.id, "approve", actor="reviewer")
    latest = service.snapshot()
    assert latest.sha256 != original.sha256 and len(latest.items) == 3000
    restarted = DynamoRepository(
        persisted.table, S3SnapshotBodies(aws_session.client("s3"), persisted.bodies.bucket)
    )
    assert restarted.read()["reviews"][pending.id]["decision"] == "approved"
    assert restarted.storage.get("approved_snapshots", original.sha256) == original.model_dump()
    assert persisted.bodies.get(pointer["s3_key"]) == body


def test_failed_staging_never_publishes_partial_knowledge(persisted, monkeypatch):
    state = corpus(2)
    persisted.commit(persisted.read(), state)
    before = persisted.read()
    after = deepcopy(before)
    after["items"]["i00000"]["statement"] = "unpublished change"
    after["reviews"]["r00000"]["decision"] = "rejected"
    stage = persisted._stage_rows

    def partial(id, rows):
        stage(id, rows[:1])
        raise RuntimeError("interrupted batch")

    monkeypatch.setattr(persisted, "_stage_rows", partial)
    with pytest.raises(RuntimeError, match="interrupted"):
        persisted.commit(before, after)
    assert persisted.read() == before
    monkeypatch.setattr(persisted, "_stage_rows", stage)
    persisted.commit(before, after)
    assert persisted.read()["items"]["i00000"]["statement"] == "unpublished change"


def test_publish_cas_rejects_losing_writer_and_keeps_pinned_reader(persisted, monkeypatch):
    state = corpus(2)
    persisted.commit(persisted.read(), state)
    before = persisted.read()
    losing, winning = deepcopy(before), deepcopy(before)
    losing["items"]["i00000"]["statement"] = "loser"
    winning["items"]["i00000"]["statement"] = "winner"
    writer = DynamoRepository(persisted.table, persisted.bodies)
    publish = persisted._publish

    def race(previous, head):
        writer.commit(before, winning)
        publish(previous, head)

    monkeypatch.setattr(persisted, "_publish", race)
    with pytest.raises(ConcurrentUpdate):
        persisted.commit(before, losing)
    assert persisted.read()["items"]["i00000"]["statement"] == "winner"
    pinned = persisted._head()
    monkeypatch.setattr(persisted, "_head", lambda: pinned)
    later = writer.read()
    next_state = deepcopy(later)
    next_state["items"]["i00000"]["statement"] = "later"
    writer.commit(later, next_state)
    assert persisted.read()["items"]["i00000"]["statement"] == "winner"
    assert writer.read()["items"]["i00000"]["statement"] == "later"


def test_snapshot_immutable_write_missing_body_and_integrity_fail_closed(persisted, monkeypatch):
    snapshot = {"sha256": digest([]), "items": []}
    saved = persisted._save_pointer
    monkeypatch.setattr(persisted, "_save_pointer", Mock(side_effect=RuntimeError("lost response")))
    with pytest.raises(RuntimeError):
        persisted.save_snapshot(snapshot)
    assert persisted.storage.get("approved_snapshots", snapshot["sha256"]) is None
    monkeypatch.setattr(persisted, "_save_pointer", saved)
    persisted.save_snapshot(snapshot)
    persisted.save_snapshot(snapshot)
    key = snapshot_key(snapshot["sha256"])
    with pytest.raises(ValueError, match="differs"):
        persisted.bodies.put(key, b"different")
    assert persisted.storage.get("approved_snapshots", snapshot["sha256"]) == snapshot
    # Simulate external corruption: pointer verification catches it before use.
    persisted.bodies.client.put_object(Bucket=persisted.bodies.bucket, Key=key, Body=b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        persisted.storage.get("approved_snapshots", snapshot["sha256"])
    persisted.bodies.client.delete_object(Bucket=persisted.bodies.bucket, Key=key)
    with pytest.raises(KeyError):
        persisted.storage.get("approved_snapshots", snapshot["sha256"])


def test_published_rows_fail_closed_if_a_row_is_missing(persisted):
    persisted.commit(persisted.read(), corpus(2))
    head = persisted._head()
    persisted.records.delete(f"extraction_rows:{head['head']}", "0000000000")
    with pytest.raises(ValueError, match="incomplete"):
        persisted.read()


def test_memory_snapshot_body_survives_repository_recreation():
    from kloop.adapters.memory import MemoryStorage
    from kloop.extract.repository import Repository

    records = MemoryStorage()
    snapshot = {"sha256": digest([]), "items": []}
    Repository(records).save_snapshot(snapshot)
    assert Repository(records).storage.get("approved_snapshots", snapshot["sha256"]) == snapshot
