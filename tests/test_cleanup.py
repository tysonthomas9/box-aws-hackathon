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


def test_owned_delete_and_retry_after_not_found(ledger):
    ledger.reserve("job", "bedrock_import", "owned-job")
    ledger.resolve("job", "arn:aws:bedrock:us-east-2:123456789012:imported-model/owned")
    session, bedrock = clients()
    bedrock.list_tags_for_resource.return_value = {
        "tags": [{"key": "deployment", "value": "owned"}]
    }
    cleanup(ledger, session)
    bedrock.delete_imported_model.assert_called_once()
    assert ledger.entries() == []
    ledger.reserve("job", "bedrock_import", "owned-job")
    ledger.resolve("job", "arn:aws:bedrock:us-east-2:123456789012:imported-model/owned")
    bedrock.list_tags_for_resource.side_effect = bedrock.exceptions.ResourceNotFoundException()
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
    with pytest.raises(
        ledger.storage._table.meta.client.exceptions.ConditionalCheckFailedException
    ):
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
