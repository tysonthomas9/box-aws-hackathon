"""Read-only joins expose lock authority, recorded costs and honest source activity."""

from types import SimpleNamespace

import pytest

from kloop.schemas import ModelVersion
from kloop.sync.state import SyncState
from kloop.train.budget import generation_id
from kloop.train.config import TrainingConfig
from kloop.train.state import DynamoTrainingStore
from kloop.web.sources import source_activity
from kloop.web.training import training_control


@pytest.fixture
def activity_table(aws_session):
    return aws_session.resource("dynamodb").create_table(
        TableName="web-activity",
        KeySchema=[
            {"AttributeName": k, "KeyType": t} for k, t in (("pk", "HASH"), ("sk", "RANGE"))
        ],
        AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k in ("pk", "sk")],
        BillingMode="PAY_PER_REQUEST",
    )


def test_training_lock_is_authority_even_without_a_version_and_after_expiry(activity_table):
    store = DynamoTrainingStore(activity_table)
    assert training_control(store, [], 100)["locked"] is False
    store.acquire("active", 100)
    for now, expired in ((101, False), (15000, True)):
        control = training_control(store, [], now)
        assert control["locked"] is True
        assert control["owner"] == "active"
        assert control["expired"] is expired
    assert store.lock()["owner"] == "active"


def test_training_cost_reports_recorded_recipe_helper_spend_only(activity_table):
    config = TrainingConfig()
    snapshot = "a" * 64
    generation = generation_id(snapshot, config)
    activity_table.put_item(
        Item={
            "pk": "training_helper_budgets",
            "sk": generation,
            "spent_nano": 1234500000,
        }
    )
    store = DynamoTrainingStore(activity_table)
    version = ModelVersion(
        id="v1",
        manifest={
            "snapshot_hash": snapshot,
            "config": config.model_dump(mode="json"),
        },
    )
    historical = ModelVersion(id="old")
    value = training_control(store, [version, historical], 100)
    assert value["progress"] == {
        "v1": {"helper_spend_usd": 1.2345},
        "old": {"helper_spend_usd": None},
    }
    assert store.versions() == []  # A read cannot create/update a version or budget.


def test_source_activity_joins_receipt_and_current_file_reviews_without_inventing_history(
    activity_table,
):
    state = SyncState(activity_table, activity_table)
    state.receive("folder", "event", 100, event_type="FILE.UPLOADED")
    state.receive("folder", "legacy-event", 90)
    state.complete("folder", "legacy-event", 101)
    runs = [
        {
            "id": "new",
            "event_id": "event",
            "changed_files": [
                {"file_id": "f", "name": "guide.txt", "action": "added", "items_extracted": 2},
            ],
        },
        {"id": "old", "event_id": None},
    ]
    result = source_activity(
        [{"file_id": "f"}],
        runs,
        activity_table,
        "folder",
        [SimpleNamespace(source_file_id="f"), SimpleNamespace(source_file_id="f")],
    )
    assert result["runs"][0]["webhook"] == {
        "event_id": "event",
        "received_at": 100,
        "event_type": "FILE.UPLOADED",
        "pending": True,
    }
    assert result["runs"][0]["changed_files"][0]["waiting_review"] == 2
    assert result["files"][0]["waiting_review"] == 2
    assert result["runs"][1]["webhook"] is None
    assert "changed_files" not in result["runs"][1]
    assert result["events"][1]["event_type"] is None
    assert result["events"][1]["pending"] is False
    assert "waiting_review" not in runs[0]["changed_files"][0]  # No stored history mutation.
