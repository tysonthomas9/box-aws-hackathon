"""Owner-fenced training lock and atomic promotion; TTL is never the lock authority."""

import json
from typing import Any

from boto3.dynamodb.conditions import Attr

from kloop.adapters.aws import DynamoStorage
from kloop.schemas import ModelVersion

# Lambda's configured 900-second maximum plus a clock/transport safety margin.
INVOCATION_SECONDS = 930


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
                Item={
                    "pk": "training_control",
                    "sk": "lock",
                    "owner": owner,
                    "until": now + 14400,
                },
                ConditionExpression=Attr("pk").not_exists(),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise TrainingBusy("Training already active; expired locks require recovery") from exc

    def assert_owner(self, owner: str) -> None:
        if (self.lock() or {}).get("owner") != owner:
            raise TrainingBusy("Training lock belongs to another request")

    def assert_active(self, owner: str) -> None:
        self.assert_owner(owner)
        if self.table.get_item(
            Key={"pk": "training_cancelled", "sk": owner}, ConsistentRead=True
        ).get("Item"):
            raise TrainingBusy("Training version is cancelled")

    def begin_invocation(self, owner: str, token: str, now: int) -> None:
        """Admission and cancellation are serialized by the same DynamoDB transaction."""
        try:
            self.table.meta.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": {"pk": "training_control", "sk": "lock"},
                            "ConditionExpression": "#owner = :owner",
                            "UpdateExpression": "SET invocation_tracking = :tracked",
                            "ExpressionAttributeNames": {"#owner": "owner"},
                            "ExpressionAttributeValues": {":owner": owner, ":tracked": True},
                        }
                    },
                    {
                        "ConditionCheck": {
                            "TableName": self.table.name,
                            "Key": {"pk": "training_cancelled", "sk": owner},
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": {
                                "pk": f"training_invocations:{owner}",
                                "sk": token,
                                "payload": json.dumps({"until": now + INVOCATION_SECONDS}),
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                ]
            )
        except self.table.meta.client.exceptions.TransactionCanceledException as exc:
            raise TrainingBusy("Training invocation refused: owner changed or cancelled") from exc

    def end_invocation(self, owner: str, token: str) -> None:
        self.table.delete_item(Key={"pk": f"training_invocations:{owner}", "sk": token})

    def cancel(self, owner: str, now: int) -> dict:
        lock = self.lock() or {}
        # Old/untracked executions require one full Lambda lifetime after the fence.
        tracked = lock.get("owner") == owner and lock.get("invocation_tracking", False)
        return self.table.update_item(
            Key={"pk": "training_cancelled", "sk": owner},
            UpdateExpression=(
                "SET cancelled_at = if_not_exists(cancelled_at, :now), "
                "quiet_until = if_not_exists(quiet_until, :until)"
            ),
            ExpressionAttributeValues={
                ":now": now,
                ":until": now if tracked else now + INVOCATION_SECONDS,
            },
            ReturnValues="ALL_NEW",
        )["Attributes"]

    def settled(self, owner: str, now: int) -> bool:
        fence = self.table.get_item(
            Key={"pk": "training_cancelled", "sk": owner}, ConsistentRead=True
        ).get("Item")
        return bool(
            fence
            and now >= fence["quiet_until"]
            and all(
                now >= row["until"] for row in self.storage.list(f"training_invocations:{owner}")
            )
        )

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
                            "Key": {"pk": "training_cancelled", "sk": version.id},
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
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
