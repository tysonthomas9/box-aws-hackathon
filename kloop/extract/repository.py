"""Row-based knowledge and review commits, atomically published by a CAS fence.

Each commit stages immutable changed item/review/source/batch rows and a manifest.
Only after all writes succeed does a single revision-CAS publish the head. Reads
follow that pinned head and replay paginated commit deltas, never staging rows.
Partial/losing writes remain unpublished and cannot affect decisions or sync
checkpoints. Snapshot bodies live outside DynamoDB; only hash pointers are rows.
"""

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

from boto3.dynamodb.conditions import Attr

from kloop.extract.hashing import digest
from kloop.extract.snapshots import (
    SnapshotStorage,
    StorageSnapshotBodies,
    encode_snapshot,
    snapshot_key,
)


class ConcurrentUpdate(RuntimeError):
    pass


def empty_state():
    return {"revision": 0, "items": {}, "reviews": {}, "batches": {}}


class Repository:
    def __init__(self, storage, snapshot_bodies=None):
        self.records = storage
        self.bodies = (
            snapshot_bodies if snapshot_bodies is not None else StorageSnapshotBodies(storage)
        )
        self.storage = SnapshotStorage(storage, self.bodies)

    def _head(self):
        head = self.records.get("extraction", "knowledge")
        if head is not None and head.get("format") != 1:
            raise ValueError("Legacy aggregate extraction state requires explicit migration")
        return head

    def _read_rows(self, commit_id, count):
        return [self.records.get(f"extraction_rows:{commit_id}", f"{i:010d}") for i in range(count)]

    def read(self) -> dict:
        head = self._head()
        if head is None:
            return empty_state()
        commits, seen, id = [], set(), head["head"]
        while id is not None:
            if id in seen:
                raise ValueError("Extraction commit chain contains a cycle")
            seen.add(id)
            manifest = self.records.get("extraction_commits", id)
            if manifest is None:
                raise ValueError("Published extraction commit manifest is missing")
            commits.append((id, manifest))
            id = manifest["parent"]
        state = empty_state()
        for id, manifest in reversed(commits):
            if manifest["revision"] != state["revision"] + 1:
                raise ValueError("Extraction commit chain has a revision gap")
            rows = self._read_rows(id, manifest["row_count"])
            if len(rows) != manifest["row_count"] or digest(rows) != manifest["rows_sha256"]:
                raise ValueError("Published extraction rows are incomplete or corrupted")
            fields = {*manifest["maps"], *manifest["scalars"], "revision"}
            state = {key: value for key, value in state.items() if key in fields}
            state.update(manifest["scalars"])
            for key in manifest["maps"]:
                if not isinstance(state.get(key), dict):
                    state[key] = {}
            for row in rows:
                if row["deleted"]:
                    state[row["collection"]].pop(row["id"], None)
                else:
                    state[row["collection"]][row["id"]] = row["value"]
            state["revision"] = manifest["revision"]
        if state["revision"] != head["revision"] or digest(state) != head["state_sha256"]:
            raise ValueError("Extraction state failed integrity check")
        return state

    def _stage_rows(self, commit_id, rows):
        for index, row in enumerate(rows):
            self.records.put(f"extraction_rows:{commit_id}", f"{index:010d}", row)

    def _publish(self, previous, head):
        if self._head() != previous:
            raise ConcurrentUpdate("Knowledge changed; retry from current state")
        self.records.put("extraction", "knowledge", head)

    def commit(self, before: dict, after: dict) -> None:
        previous = self._head()
        expected = previous["state_sha256"] if previous else digest(empty_state())
        if digest(before) != expected:
            raise ConcurrentUpdate("Knowledge changed; retry from current state")
        after = deepcopy(after)
        after["revision"] = before["revision"] + 1
        maps = [key for key, value in after.items() if isinstance(value, dict)]
        rows = []
        for collection in maps:
            old = before.get(collection, {})
            if not isinstance(old, dict):
                old = {}
            for id, value in after[collection].items():
                if id not in old or old[id] != value:
                    rows.append(
                        {"collection": collection, "id": id, "deleted": False, "value": value}
                    )
            for id in old.keys() - after[collection].keys():
                rows.append({"collection": collection, "id": id, "deleted": True})
        # Per-row bound only: the corpus and snapshot may span many megabytes.
        if any(len(json.dumps(row).encode()) > 350_000 for row in rows):
            raise ValueError("An extraction row exceeds the 350 KB per-row bound")
        id = uuid4().hex
        self._stage_rows(id, rows)
        manifest = {
            "parent": previous["head"] if previous else None,
            "revision": after["revision"],
            "maps": maps,
            "scalars": {k: v for k, v in after.items() if k not in {*maps, "revision"}},
            "row_count": len(rows),
            "rows_sha256": digest(rows),
        }
        self.records.put("extraction_commits", id, manifest)
        self._publish(
            previous,
            {"format": 1, "revision": after["revision"], "head": id, "state_sha256": digest(after)},
        )

    def _save_pointer(self, sha, pointer):
        previous = self.records.get("approved_snapshots", sha)
        if previous is not None and previous != pointer:
            raise ValueError("Snapshot hash collision or corrupted snapshot pointer")
        if previous is None:
            self.records.put("approved_snapshots", sha, pointer)

    def save_snapshot(self, snapshot: dict) -> None:
        body = encode_snapshot(snapshot)
        sha, key = snapshot["sha256"], snapshot_key(snapshot["sha256"])
        self.bodies.put(key, body)
        self._save_pointer(
            sha,
            {
                "format": 1,
                "sha256": sha,
                "s3_key": key,
                "body_sha256": hashlib.sha256(body).hexdigest(),
            },
        )


class DynamoRepository(Repository):
    def __init__(self, table, snapshot_bodies=None):
        from kloop.adapters.aws import DynamoStorage

        if snapshot_bodies is None:
            raise ValueError("Configure immutable S3 snapshot bodies for DynamoRepository")
        super().__init__(DynamoStorage(table), snapshot_bodies)
        self.table = table

    def _read_rows(self, commit_id, count):
        # DynamoStorage.list exhausts the Query paginator with consistent reads.
        return self.records.list(f"extraction_rows:{commit_id}")

    def _stage_rows(self, commit_id, rows):
        with self.table.batch_writer() as batch:
            for index, row in enumerate(rows):
                batch.put_item(
                    Item={
                        "pk": f"extraction_rows:{commit_id}",
                        "sk": f"{index:010d}",
                        "payload": json.dumps(row, allow_nan=False),
                    }
                )

    def _publish(self, previous, head):
        condition = (
            Attr("revision").eq(previous["revision"]) if previous else Attr("pk").not_exists()
        )
        try:
            self.table.put_item(
                Item={
                    "pk": "extraction",
                    "sk": "knowledge",
                    "revision": head["revision"],
                    "payload": json.dumps(head, allow_nan=False),
                },
                ConditionExpression=condition,
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ConcurrentUpdate("Knowledge changed; retry from current state") from exc

    def _save_pointer(self, sha, pointer):
        try:
            self.table.put_item(
                Item={
                    "pk": "approved_snapshots",
                    "sk": sha,
                    "payload": json.dumps(pointer, allow_nan=False),
                },
                ConditionExpression=Attr("pk").not_exists(),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            if self.records.get("approved_snapshots", sha) != pointer:
                raise ValueError("Snapshot hash collision or corrupted snapshot pointer") from None
