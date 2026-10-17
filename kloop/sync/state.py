"""Atomic DynamoDB receipts and folder leases, separate from ordinary JSON storage."""

import json
from typing import Any

from boto3.dynamodb.conditions import Attr, Key


class SyncState:
    def __init__(self, receipts: Any, locks: Any):
        self.receipts = receipts
        self.locks = locks

    def receive(self, folder_id: str, event_id: str, now: int) -> bool:
        # Pending work deliberately has NO TTL. Only completed receipts may expire.
        try:
            self.receipts.put_item(
                Item={"pk": f"receipts:{folder_id}", "sk": event_id, "received_at": now},
                ConditionExpression=Attr("pk").not_exists(),
            )
            return True
        except self.receipts.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def pending(self, folder_id: str) -> list[str]:
        pages = self.receipts.meta.client.get_paginator("query").paginate(
            TableName=self.receipts.name,
            KeyConditionExpression=Key("pk").eq(f"receipts:{folder_id}"),
            ConsistentRead=True,
        )
        return [r["sk"] for p in pages for r in p.get("Items", []) if "expires_at" not in r]

    def complete(self, folder_id: str, event_id: str, now: int) -> None:
        self.receipts.update_item(
            Key={"pk": f"receipts:{folder_id}", "sk": event_id},
            UpdateExpression="SET expires_at = :ttl",
            ExpressionAttributeValues={":ttl": now + 7 * 86400},
            ConditionExpression=Attr("pk").exists(),
        )

    def acquire(self, folder_id: str, owner: str, now: int) -> bool:
        # Lambda has a hard 900s execution limit; lease outlives any old invocation.
        try:
            self.locks.put_item(
                Item={"pk": "sync_locks", "sk": folder_id, "owner": owner, "until": now + 960},
                ConditionExpression=Attr("pk").not_exists() | Attr("until").lt(now),
            )
            return True
        except self.locks.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def release(self, folder_id: str, owner: str) -> None:
        try:
            self.locks.delete_item(
                Key={"pk": "sync_locks", "sk": folder_id},
                ConditionExpression=Attr("owner").eq(owner),
            )
        except self.locks.meta.client.exceptions.ConditionalCheckFailedException:
            pass  # Never release a successor's lease.


class LambdaDispatch:
    def __init__(self, client: Any, function_name: str):
        self.client = client
        self.function_name = function_name

    def __call__(self, trigger: str, event_id: str | None = None) -> None:
        result = self.client.invoke(
            FunctionName=self.function_name,
            InvocationType="Event",
            Payload=json.dumps({"source": trigger, "event_id": event_id}).encode(),
        )
        body = result.get("Payload")
        if body is not None:
            body.close()
        if result["StatusCode"] != 202:
            raise RuntimeError("Sync dispatch was not accepted")
