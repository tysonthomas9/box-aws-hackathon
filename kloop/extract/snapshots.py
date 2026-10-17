"""Immutable content-addressed snapshot bodies and transparent pointer reads."""

import hashlib
import json
import re

from botocore.exceptions import ClientError

from kloop.extract.hashing import digest


def snapshot_key(sha: str) -> str:
    if re.fullmatch(r"[a-f0-9]{64}", sha) is None:
        raise ValueError("Invalid snapshot hash")
    return f"extraction/snapshots/{sha}.json"


def encode_snapshot(snapshot: dict) -> bytes:
    if digest(snapshot["items"]) != snapshot["sha256"]:
        raise ValueError("Invalid or corrupted snapshot hash")
    snapshot_key(snapshot["sha256"])
    return json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


class StorageSnapshotBodies:
    """Persist bodies with injected memory/file fakes; Dynamo uses S3 instead."""

    def __init__(self, records):
        self.records = records

    def get(self, key: str) -> bytes:
        value = self.records.get("snapshot_bodies", key)
        if value is None:
            raise KeyError(key)
        return value["body"].encode()

    def put(self, key: str, body: bytes) -> None:
        previous = self.records.get("snapshot_bodies", key)
        value = {"body": body.decode()}
        if previous is not None and previous != value:
            raise ValueError("Immutable snapshot body differs")
        if previous is None:
            self.records.put("snapshot_bodies", key, value)


class S3SnapshotBodies:
    def __init__(self, client, bucket: str):
        if not bucket:
            raise ValueError("Configure KLOOP_ARTIFACT_BUCKET for approved snapshots")
        self.client, self.bucket = client, bucket

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise KeyError(key) from exc
        with response["Body"] as stream:
            return stream.read()

    def put(self, key: str, body: bytes) -> None:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as exc:
            # S3 does not expose a modeled PreconditionFailed exception.
            if exc.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
                raise
            if self.get(key) != body:
                raise ValueError("Immutable snapshot body differs") from exc


class SnapshotStorage:
    """Preserve Storage.get(approved_snapshots, hash) for training and web callers.

    The records adapter holds only a small immutable pointer. Bodies are verified
    on every read; a corrupt/missing object never becomes a training snapshot.
    """

    def __init__(self, records, bodies):
        self.records, self.bodies = records, bodies

    def get(self, collection, id):
        value = self.records.get(collection, id)
        if collection != "approved_snapshots" or value is None:
            return value
        if (
            value.get("sha256") != id
            or value.get("s3_key") != snapshot_key(id)
            or value.get("format") != 1
        ):
            raise ValueError("Invalid approved snapshot pointer")
        body = self.bodies.get(value["s3_key"])
        if hashlib.sha256(body).hexdigest() != value["body_sha256"]:
            raise ValueError("Snapshot body failed integrity check")
        snapshot = json.loads(body)
        if snapshot["sha256"] != id or encode_snapshot(snapshot) != body:
            raise ValueError("Snapshot content failed integrity check")
        return snapshot

    def put(self, collection, id, value):
        if collection == "approved_snapshots":
            raise ValueError("Use Repository.save_snapshot for immutable snapshots")
        return self.records.put(collection, id, value)

    def delete(self, collection, id):
        if collection == "approved_snapshots":
            raise ValueError("Approved snapshots are immutable")
        return self.records.delete(collection, id)

    def list(self, collection):
        if collection == "approved_snapshots":
            return [self.get(collection, row["sha256"]) for row in self.records.list(collection)]
        return self.records.list(collection)
