"""Destroy must preserve POC resources and stop before losing uncertain creates."""

from unittest.mock import Mock

import boto3
import pytest
from moto import mock_aws

from kloop.cleanup import CleanupLedger, cleanup


@pytest.fixture
def ledger():
    with mock_aws():
        db = boto3.resource("dynamodb", region_name="us-east-2")
        table = db.create_table(
            TableName="cleanup",
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield CleanupLedger(table, "owned")


def clients():
    bedrock = Mock()
    bedrock.exceptions.ResourceNotFoundException = type("Missing", (Exception,), {})
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    session = Mock()
    session.client.side_effect = lambda name: {"bedrock": bedrock, "sts": sts}[name]
    return session, bedrock


def test_uncertain_create_blocks_destroy(ledger):
    ledger.reserve("job", "bedrock_import", "owned-job")
    session, bedrock = clients()
    with pytest.raises(RuntimeError, match="Reconcile"):
        cleanup(ledger, session)
    bedrock.delete_imported_model.assert_not_called()
    assert len(ledger.entries()) == 1


def test_foreign_tag_blocks_delete(ledger):
    ledger.reserve("job", "bedrock_import", "owned-job")
    ledger.resolve("job", "arn:aws:bedrock:us-east-2:123456789012:imported-model/poc")
    session, bedrock = clients()
    bedrock.list_tags_for_resource.return_value = {"tags": [{"key": "deployment", "value": "poc"}]}
    with pytest.raises(ValueError, match="not tagged"):
        cleanup(ledger, session)
    bedrock.delete_imported_model.assert_not_called()
    assert len(ledger.entries()) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_owned_delete_and_retry_after_not_found(ledger, missing):
    ledger.reserve("job", "bedrock_import", "owned-job")
    ledger.resolve("job", "arn:aws:bedrock:us-east-2:123456789012:imported-model/owned")
    session, bedrock = clients()
    bedrock.list_tags_for_resource.return_value = {
        "tags": [{"key": "deployment", "value": "owned"}]
    }
    if missing:
        bedrock.list_tags_for_resource.side_effect = bedrock.exceptions.ResourceNotFoundException()
    cleanup(ledger, session)
    if not missing:
        bedrock.delete_imported_model.assert_called_once()
    assert ledger.entries() == []
    cleanup(ledger, session)
    assert ledger.entries() == []


def test_box_cleanup_is_required_and_scoped(ledger):
    ledger.reserve("hook", "box_webhook", "owned-folder")
    ledger.resolve("hook", "1234")
    session, _ = clients()
    with pytest.raises(RuntimeError, match="adapter required"):
        cleanup(ledger, session)
    callback = Mock()
    cleanup(ledger, session, callback)
    callback.assert_called_once_with("1234")
    assert ledger.entries() == []


def test_reservation_cannot_overwrite_ownership(ledger):
    ledger.reserve("job", "bedrock_import", "first")
    with pytest.raises(ledger.storage._table.meta.client.exceptions.TransactionCanceledException):
        ledger.reserve("job", "bedrock_import", "second")
    assert ledger.entries()[0]["name"] == "first"


def test_deletion_failure_retains_retry_record(ledger):
    ledger.reserve("job", "bedrock_import", "owned-job")
    ledger.resolve("job", "arn:aws:bedrock:us-east-2:123456789012:imported-model/owned")
    session, bedrock = clients()
    bedrock.list_tags_for_resource.return_value = {
        "tags": [{"key": "deployment", "value": "owned"}]
    }
    bedrock.delete_imported_model.side_effect = RuntimeError("service unavailable")
    with pytest.raises(RuntimeError, match="service unavailable"):
        cleanup(ledger, session)
    assert len(ledger.entries()) == 1


def test_foreign_region_never_reaches_delete(ledger):
    ledger.reserve("job", "bedrock_import", "owned-job")
    ledger.resolve("job", "arn:aws:bedrock:us-west-2:123456789012:imported-model/poc")
    session, bedrock = clients()
    with pytest.raises(ValueError, match="selected Region"):
        cleanup(ledger, session)
    bedrock.list_tags_for_resource.assert_not_called()
    bedrock.delete_imported_model.assert_not_called()


def test_destroy_fence_stops_new_creates_but_retains_pending(ledger):
    ledger.reserve("active", "box_webhook", "folder")
    session, _ = clients()
    callback = Mock()
    with pytest.raises(RuntimeError, match="Reconcile"):
        cleanup(ledger, session, callback)
    with pytest.raises(ledger.storage._table.meta.client.exceptions.TransactionCanceledException):
        ledger.reserve("late", "box_webhook", "folder")
    callback.assert_not_called()
    assert [row["key"] for row in ledger.entries()] == ["active"]
    ledger.resolve("active", "123")
    cleanup(ledger, session, callback)
    callback.assert_called_once_with("123")
    assert ledger.entries() == []


def test_fence_is_present_before_cleanup_snapshot(ledger, monkeypatch):
    original = ledger.entries

    def snapshot():
        with pytest.raises(
            ledger.storage._table.meta.client.exceptions.TransactionCanceledException
        ):
            ledger.reserve("late", "box_webhook", "folder")
        return original()

    monkeypatch.setattr(ledger, "entries", snapshot)
    cleanup(ledger, clients()[0])


def test_resolve_cannot_change_identity_or_restore_deleted_row(ledger, monkeypatch):
    ledger.reserve("hook", "box_webhook", "folder")
    ledger.resolve("hook", "123")
    ledger.resolve("hook", "123")
    with pytest.raises(ValueError, match="another resource"):
        ledger.resolve("hook", "456")
    assert ledger.entries()[0]["resource_id"] == "123"
    table = ledger.storage._table
    original = table.put_item

    def stale(**kwargs):
        table.delete_item(Key={"pk": ledger.collection, "sk": "hook"})
        return original(**kwargs)

    monkeypatch.setattr(table, "put_item", stale)
    with pytest.raises(table.meta.client.exceptions.ConditionalCheckFailedException):
        ledger.resolve("hook", "123")
    assert ledger.entries() == []


def test_cleanup_cannot_remove_replaced_identity(ledger):
    ledger.reserve("hook", "box_webhook", "folder")
    ledger.resolve("hook", "123")
    row = ledger.entries()[0]
    ledger.storage.put(ledger.collection, "hook", {**row, "resource_id": "unexpected"})
    with pytest.raises(
        ledger.storage._table.meta.client.exceptions.ConditionalCheckFailedException
    ):
        ledger.remove(row)
    assert ledger.entries()[0]["resource_id"] == "unexpected"


@pytest.mark.parametrize("status", ["InProgress", "Completed"])
def test_training_destroy_stops_only_the_recorded_job(ledger, status):
    ledger.reserve("gpu", "sagemaker_training", "owned-job")
    ledger.resolve("gpu", "arn:aws:sagemaker:us-east-2:123456789012:training-job/owned-job")
    session, bedrock = clients()
    sagemaker = Mock()
    sagemaker.describe_training_job.return_value = {"TrainingJobStatus": status}
    sagemaker.exceptions.ResourceNotFound = type("MissingJob", (Exception,), {})
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    session.client.side_effect = lambda name: {
        "bedrock": bedrock,
        "sagemaker": sagemaker,
        "sts": sts,
    }[name]
    cleanup(ledger, session)
    if status == "InProgress":
        sagemaker.stop_training_job.assert_called_once_with(TrainingJobName="owned-job")
    else:
        sagemaker.stop_training_job.assert_not_called()
    assert not ledger.entries()


def test_training_destroy_rejects_foreign_job_arn(ledger):
    ledger.reserve("gpu", "sagemaker_training", "owned-job")
    ledger.resolve("gpu", "arn:aws:sagemaker:us-west-2:123456789012:training-job/owned-job")
    with pytest.raises(ValueError, match="selected Region"):
        cleanup(ledger, clients()[0])
    assert len(ledger.entries()) == 1
