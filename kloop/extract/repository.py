"""Atomic knowledge/review state for the bounded demo corpus.

One DynamoDB record makes decisions and effective items atomic, including on
ambiguous-write retries. A revision CAS rejects overlapping writers. Snapshots
are separately content-addressed and never overwritten. Fail before DynamoDB's
400 KiB limit; this demo store is intentionally bounded, not a bulk ingest store.
"""

import json
from copy import deepcopy
from typing import Any

from boto3.dynamodb.conditions import Attr

from kloop.extract.hashing import digest
from kloop.ports import Storage


class ConcurrentUpdate(RuntimeError):
    pass


def empty_state():
    return {"revision": 0, "items": {}, "reviews": {}, "batches": {}}


class Repository:
    def __init__(self, storage: Storage):
        self.storage = storage

    def read(self) -> dict:
        return self.storage.get("extraction", "knowledge") or empty_state()

    def commit(self, before: dict, after: dict) -> None:
        if self.read() != before:
            raise ConcurrentUpdate("Knowledge changed; retry from current state")
        after = deepcopy(after)
        after["revision"] = before["revision"] + 1
        if len(json.dumps(after).encode()) > 350_000:
            raise ValueError("Demo knowledge state exceeds its 350 KB bound")
        self.storage.put("extraction", "knowledge", after)

    def save_snapshot(self, snapshot: dict) -> None:
        if digest(snapshot["items"]) != snapshot["sha256"]:
            raise ValueError("Invalid or corrupted snapshot hash")
        key = snapshot["sha256"]
        previous = self.storage.get("approved_snapshots", key)
        if previous is not None and previous != snapshot:
            raise ValueError("Snapshot hash collision or corrupted snapshot")
        if previous is None:
            self.storage.put("approved_snapshots", key, snapshot)


class DynamoRepository(Repository):
    def __init__(self, table: Any):
        from kloop.adapters.aws import DynamoStorage

        super().__init__(DynamoStorage(table))
        self.table = table

    def commit(self, before: dict, after: dict) -> None:
        after = deepcopy(after)
        after["revision"] = before["revision"] + 1
        payload = json.dumps(after, allow_nan=False)
        if len(payload.encode()) > 350_000:
            raise ValueError("Demo knowledge state exceeds its 350 KB bound")
        try:
            self.table.put_item(
                Item={
                    "pk": "extraction",
                    "sk": "knowledge",
                    "payload": payload,
                    "revision": after["revision"],
                },
                ConditionExpression=(
                    Attr("revision").eq(before["revision"])
                    if before["revision"]
                    else Attr("pk").not_exists()
                ),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ConcurrentUpdate("Knowledge changed; retry from current state") from exc

    def save_snapshot(self, snapshot: dict) -> None:
        if digest(snapshot["items"]) != snapshot["sha256"]:
            raise ValueError("Invalid or corrupted snapshot hash")
        try:
            self.table.put_item(
                Item={
                    "pk": "approved_snapshots",
                    "sk": snapshot["sha256"],
                    "payload": json.dumps(snapshot, allow_nan=False),
                },
                ConditionExpression=Attr("pk").not_exists(),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            if self.storage.get("approved_snapshots", snapshot["sha256"]) != snapshot:
                raise ValueError("Snapshot hash collision or corrupted snapshot") from None
