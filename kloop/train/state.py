"""Owner-fenced training lock and atomic promotion; TTL is never the lock authority."""

import json
from typing import Any

from boto3.dynamodb.conditions import Attr

from kloop.adapters.aws import DynamoStorage
from kloop.schemas import ModelVersion


class TrainingBusy(RuntimeError):
    pass


class DynamoTrainingStore:
    def __init__(self, table: Any):
        self.table = table
        self.storage = DynamoStorage(table)

    def get(self, version_id: str) -> ModelVersion | None:
        value = self.storage.get("model_versions", version_id)
        return ModelVersion.model_validate(value) if value else None

    def save(self, version: ModelVersion) -> None:
        self.storage.put("model_versions", version.id, version.model_dump(mode="json"))

    def versions(self) -> list[ModelVersion]:
        return [ModelVersion.model_validate(v) for v in self.storage.list("model_versions")]

    def current(self) -> str | None:
        return (
            self.table.get_item(
                Key={"pk": "training_control", "sk": "current"}, ConsistentRead=True
            )
            .get("Item", {})
            .get("version_id")
        )

    def lock(self) -> dict | None:
        return self.table.get_item(
            Key={"pk": "training_control", "sk": "lock"}, ConsistentRead=True
        ).get("Item")

    def acquire(self, owner: str, now: int) -> None:
        try:
            self.table.put_item(
                Item={"pk": "training_control", "sk": "lock", "owner": owner, "until": now + 14400},
                ConditionExpression=Attr("pk").not_exists(),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise TrainingBusy("Training already active; expired locks require recovery") from exc

    def assert_owner(self, owner: str) -> None:
        if (self.lock() or {}).get("owner") != owner:
            raise TrainingBusy("Training lock belongs to another request")

    def release(self, owner: str) -> None:
        try:
            self.table.delete_item(
                Key={"pk": "training_control", "sk": "lock"},
                ConditionExpression=Attr("owner").eq(owner),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            pass

    def promote(self, version: ModelVersion, expected: str | None) -> bool:
        """Pointer, version status and owner fence are one DynamoDB transaction."""
        promoted = version.model_copy(deep=True)
        promoted.status = "promoted"
        pointer = {
            "TableName": self.table.name,
            "Item": {"pk": "training_control", "sk": "current", "version_id": version.id},
        }
        if expected is None:
            pointer["ConditionExpression"] = "attribute_not_exists(pk)"
        else:
            pointer.update(
                ConditionExpression="version_id = :expected",
                ExpressionAttributeValues={":expected": expected},
            )
        try:
            self.table.meta.client.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": self.table.name,
                            "Key": {"pk": "training_control", "sk": "lock"},
                            "ConditionExpression": "#owner = :owner",
                            "ExpressionAttributeNames": {"#owner": "owner"},
                            "ExpressionAttributeValues": {":owner": version.id},
                        }
                    },
                    {"Put": pointer},
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": {
                                "pk": "model_versions",
                                "sk": version.id,
                                "payload": json.dumps(promoted.model_dump(mode="json")),
                            },
                        }
                    },
                ]
            )
        except self.table.meta.client.exceptions.TransactionCanceledException:
            # Ambiguous-write retries see the committed pointer as success.
            return self.current() == version.id
        return True
