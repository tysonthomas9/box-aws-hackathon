"""Load sealed corpus evidence into the designated stack; never creates resources."""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import boto3

from kloop.adapters.aws import DynamoStorage
from kloop.extract.hashing import digest
from kloop.extract.medical import SOURCE_FOLDER_ID
from kloop.extract.medical_corpus import Evidence, replay, save
from kloop.extract.medical_selection import select_training
from kloop.extract.repository import DynamoRepository, empty_state
from kloop.extract.snapshots import S3SnapshotBodies, SnapshotStorage


def publish(
    evidence,
    manifest,
    repository,
    records,
    bodies,
    *,
    cursors,
    expected_state_sha256=None,
    expected_revision=None,
    total=400,
    per_document=4,
):
    if manifest["status"] != "complete":
        raise ValueError("Full extraction must finish before publication")
    service = replay(evidence, manifest)
    state = service.repository.read()
    if digest(state) != manifest["state_evidence_sha256"]:
        raise ValueError("Replayed state differs from the sealed evidence")
    approved = service.snapshot()
    if digest(approved.model_dump(mode="json")) != manifest["approved_snapshot_evidence_sha256"]:
        raise ValueError("Approved snapshot differs from the sealed evidence")
    attributes = {
        row["item_id"]: row["candidate"]["attribute"] for row in state["reviews"].values()
    }
    training, selection = select_training(
        approved, attributes, total=total, per_document=per_document
    )
    if not training.items:
        raise ValueError("Training selection is empty")
    if (expected_state_sha256 is None) != (expected_revision is None):
        raise ValueError("Replacement requires both an expected state hash and revision")
    inventory = evidence.get(manifest["inventory_sha256"])
    files = {file["id"]: file for file in inventory["files"]}
    collection = f"sync_cursors:{SOURCE_FOLDER_ID}"
    old_cursors = sorted(cursors.list(collection), key=lambda row: row["file_id"])
    if any(row["file_id"] not in files for row in old_cursors):
        raise ValueError("Destination has a cursor outside the sealed source census")
    training_evidence_sha = evidence.put(training.model_dump(mode="json"))
    selection_evidence_sha = evidence.put(selection)
    before = repository.read()
    same = {k: v for k, v in before.items() if k != "revision"} == {
        k: v for k, v in state.items() if k != "revision"
    }
    archive = None
    if same:
        if expected_state_sha256 is not None:
            archive = records.get("medical_state_archives", expected_state_sha256)
            if archive is None:
                raise ValueError("Replacement retry is missing its immutable archive")
            if (
                archive["revision"] != expected_revision
                or archive["state_sha256"] != expected_state_sha256
                or archive["replacement_approved_snapshot_sha256"] != approved.sha256
            ):
                raise ValueError("Replacement retry differs from its authorized archive")
            if digest(json.loads(bodies.get(archive["state_s3_key"]))) != expected_state_sha256:
                raise ValueError("Replacement archive failed integrity check")
            if digest(json.loads(bodies.get(archive["cursor_s3_key"]))) != archive["cursor_sha256"]:
                raise ValueError("Cursor archive failed integrity check")
    elif expected_state_sha256 is not None:
        if before["revision"] != expected_revision or digest(before) != expected_state_sha256:
            raise ValueError(
                "Destination differs from the explicitly authorized state and revision"
            )
        state_key = f"extraction/archives/states/{expected_state_sha256}.json"
        state_body = json.dumps(
            before, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        cursor_sha = digest(old_cursors)
        cursor_key = f"extraction/archives/sync-cursors/{cursor_sha}.json"
        cursor_body = json.dumps(
            old_cursors, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        bodies.put(state_key, state_body)
        bodies.put(cursor_key, cursor_body)
        if bodies.get(state_key) != state_body or bodies.get(cursor_key) != cursor_body:
            raise ValueError("Unexpected-state archive readback differs")
        archive = {
            "state_sha256": expected_state_sha256,
            "revision": expected_revision,
            "state_s3_key": state_key,
            "cursor_sha256": cursor_sha,
            "cursor_s3_key": cursor_key,
            "replacement_approved_snapshot_sha256": approved.sha256,
        }
        previous = records.get("medical_state_archives", expected_state_sha256)
        if previous is not None and previous != archive:
            raise ValueError("Immutable unexpected-state archive pointer differs")
        records.put("medical_state_archives", expected_state_sha256, archive)
        # Repository retains the old immutable deltas and CAS-publishes the replacement.
        repository.commit(before, state)
    elif before == empty_state():
        # One atomic bulk publication retains every canonical automatic review decision.
        repository.commit(before, state)
    else:
        raise ValueError("Destination already has different knowledge; refusing to overwrite")
    stored = repository.read()
    if {k: v for k, v in stored.items() if k != "revision"} != {
        k: v for k, v in state.items() if k != "revision"
    }:
        raise ValueError("Published active knowledge differs from the validated corpus")
    repository.save_snapshot(approved.model_dump(mode="json"))
    repository.save_snapshot(training.model_dump(mode="json"))
    selection_sha = digest(selection)
    selection_key = f"extraction/selections/{selection_sha}.json"
    body = json.dumps(selection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    bodies.put(selection_key, body)
    if bodies.get(selection_key) != body:
        raise ValueError("Selection manifest readback differs")
    snapshots = SnapshotStorage(records, bodies)
    for snapshot in (approved, training):
        if snapshots.get("approved_snapshots", snapshot.sha256) != snapshot.model_dump(mode="json"):
            raise ValueError("Stored snapshot readback differs")
    lineage = {
        "training_snapshot_sha256": training.sha256,
        "parent_approved_snapshot_sha256": approved.sha256,
        "selection_manifest_sha256": selection_sha,
        "selection_manifest_s3_key": selection_key,
    }
    existing = records.get("medical_training_snapshots", training.sha256)
    if existing is not None and existing != lineage:
        raise ValueError("Stored training lineage differs")
    records.put("medical_training_snapshots", training.sha256, lineage)
    expected_cursors = [
        {"file_id": file["id"], "version_id": file["version_id"], "retired": False}
        for _, file in sorted(files.items())
    ]
    for cursor in expected_cursors:
        cursors.put(collection, cursor["file_id"], cursor)
    if sorted(cursors.list(collection), key=lambda row: row["file_id"]) != expected_cursors:
        raise ValueError("Sync cursor readback differs from the sealed source census")
    stats = defaultdict(lambda: Counter())
    for file in files.values():
        area = file["path"].split("/")[1]
        stats[area]["documents"] += 1
        stats[area]["extracted_items"] += manifest["documents"][file["id"]]["items"]
    pending_reasons = Counter()
    for review in state["reviews"].values():
        area = files[review["source_file_id"]]["path"].split("/")[1]
        stats[area][review["decision"]] += 1
        if review["decision"] == "pending":
            pending_reasons.update(review["reasons"])
    for entry in selection["entries"]:
        area = files[entry["source_file_id"]]["path"].split("/")[1]
        stats[area][entry["selection"]] += 1
    result = {
        **lineage,
        "source_folder_id": SOURCE_FOLDER_ID,
        "inventory_sha256": manifest["inventory_sha256"],
        "evidence_manifest_sha256": digest(manifest),
        "training_snapshot_evidence_sha256": training_evidence_sha,
        "selection_manifest_evidence_sha256": selection_evidence_sha,
        "archived_unexpected_state": archive,
        "knowledge_revision": stored["revision"],
        "sync_cursor_count": len(expected_cursors),
        "sync_cursor_inventory_sha256": digest(expected_cursors),
        "approved_items": len(approved.items),
        "training_items": len(training.items),
        "not_selected_items": len(approved.items) - len(training.items),
        "pending_reviews": sum(r["decision"] == "pending" for r in state["reviews"].values()),
        "pending_reasons": dict(pending_reasons),
        "per_folder": {area: dict(value) for area, value in sorted(stats.items())},
    }
    records.put("medical_corpus", SOURCE_FOLDER_ID, result)
    if records.get("medical_corpus", SOURCE_FOLDER_ID) != result:
        raise ValueError("Corpus publication readback differs")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path("poc/medical-corpus/evidence/full"))
    parser.add_argument("--table", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--sync-cursors-table", required=True)
    parser.add_argument("--expected-state-sha256")
    parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args()
    try:
        session = boto3.Session(profile_name="box-hackathon", region_name="us-east-2")
        s3 = session.client("s3")
        if s3.get_bucket_location(Bucket=args.bucket)["LocationConstraint"] != "us-east-2":
            raise ValueError("Artifact bucket must be in the selected Region us-east-2")
        table = session.resource("dynamodb").Table(args.table)
        if ":us-east-2:" not in table.table_arn:
            raise ValueError("Items table must be in the selected Region us-east-2")
        cursor_table = session.resource("dynamodb").Table(args.sync_cursors_table)
        if args.sync_cursors_table == args.table or ":us-east-2:" not in cursor_table.table_arn:
            raise ValueError("Use the separate sync cursor table in us-east-2")
        evidence = Evidence(args.evidence)
        seal = json.loads((args.evidence / "seal.json").read_text())
        manifest = evidence.get(seal["manifest_sha256"])
        inventory = evidence.get(manifest["inventory_sha256"])
        if inventory["folder_id"] != SOURCE_FOLDER_ID or len(inventory["files"]) != 115:
            raise ValueError("Publication requires the approved115-document source census")
        bodies = S3SnapshotBodies(s3, args.bucket)
        repository = DynamoRepository(table, bodies)
        result = publish(
            evidence,
            manifest,
            repository,
            DynamoStorage(table),
            bodies,
            cursors=DynamoStorage(cursor_table),
            expected_state_sha256=args.expected_state_sha256,
            expected_revision=args.expected_revision,
        )
        result.update(
            table=args.table, bucket=args.bucket, sync_cursors_table=args.sync_cursors_table
        )
        save(args.evidence / "publication.json", result)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(
            f"Corpus publication stopped ({type(exc).__name__}); no resources created.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
