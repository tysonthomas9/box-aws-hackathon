"""Bulk publication preserves searchable approvals and immutable training lineage."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kloop.adapters.memory import MemoryStorage
from kloop.box.client import FileInfo
from kloop.extract.hashing import digest
from kloop.extract.medical_corpus import Evidence, replay
from kloop.extract.medical_publish import publish
from kloop.extract.repository import Repository
from kloop.extract.snapshots import SnapshotStorage, StorageSnapshotBodies
from kloop.sync.service import SyncService


def corpus(tmp_path):
    evidence = Evidence(tmp_path)
    files = [
        {"id": str(i), "version_id": "v1", "path": f"company-specific/area-{i}/source.docx"}
        for i in range(2)
    ]
    manifest = {
        "status": "complete",
        "inventory_sha256": evidence.put({"folder_id": "428391006380", "files": files}),
        "documents": {},
    }
    for file in files:
        rows = [
            {
                "kind": "fact",
                "subject": file["id"],
                "attribute": f"limit_{i}",
                "statement": f"Limit {i} mg",
                "supporting_quote": f"Limit {i} mg" if i != 7 or file["id"] == "0" else "Absent",
            }
            for i in range(8)
        ]
        document = {
            "file_id": file["id"],
            "version_id": "v1",
            "name": "source.docx",
            "text": "\n".join(f"Limit {i} mg" for i in range(8)),
        }
        manifest["documents"][file["id"]] = {
            "status": "complete",
            "items": 8,
            "source_sha256": evidence.put(document),
            "rows_sha256": evidence.put(rows),
        }
    service = replay(evidence, manifest)
    manifest["state_evidence_sha256"] = evidence.put(service.repository.read())
    manifest["approved_snapshot_evidence_sha256"] = evidence.put(
        service.snapshot().model_dump(mode="json")
    )
    return evidence, manifest


def test_publication_keeps_all_clean_items_and_persists_separate_training_snapshot(tmp_path):
    evidence, manifest = corpus(tmp_path)
    records = MemoryStorage()
    bodies = StorageSnapshotBodies(records)
    repository = Repository(records, bodies)
    result = publish(
        evidence,
        manifest,
        repository,
        records,
        bodies,
        cursors=MemoryStorage(),
        total=6,
        per_document=3,
    )
    assert result["approved_items"] == 15 and result["training_items"] == 6
    assert result["not_selected_items"] == 9 and result["pending_reviews"] == 1
    assert result["pending_reasons"] == {"quote_not_in_source": 1}
    assert len(repository.read()["items"]) == 15
    assert all(row["decision"] != "rejected" for row in repository.read()["reviews"].values())
    storage = SnapshotStorage(records, bodies)
    for key, count in (("parent_approved_snapshot_sha256", 15), ("training_snapshot_sha256", 6)):
        snapshot = storage.get("approved_snapshots", result[key])
        assert len(snapshot["items"]) == count
        assert digest(snapshot["items"]) == result[key]
    selection = json.loads(bodies.get(result["selection_manifest_s3_key"]))
    assert selection["source_snapshot_sha256"] == result["parent_approved_snapshot_sha256"]
    assert selection["training_snapshot_sha256"] == result["training_snapshot_sha256"]
    assert digest(selection) == result["selection_manifest_sha256"]
    assert (
        publish(
            evidence,
            manifest,
            repository,
            records,
            bodies,
            cursors=MemoryStorage(),
            total=6,
            per_document=3,
        )
        == result
    )


def test_corrupt_sealed_state_is_rejected_before_destination_writes(tmp_path):
    evidence, manifest = corpus(tmp_path)
    manifest["state_evidence_sha256"] = "0" * 64
    records = MemoryStorage()
    bodies = StorageSnapshotBodies(records)
    with pytest.raises(ValueError, match="sealed evidence"):
        publish(
            evidence,
            manifest,
            Repository(records, bodies),
            records,
            bodies,
            cursors=MemoryStorage(),
        )
    assert records.get("extraction", "knowledge") is None


def test_existing_different_knowledge_is_never_replaced(tmp_path):
    evidence, manifest = corpus(tmp_path)
    records = MemoryStorage()
    bodies = StorageSnapshotBodies(records)
    repository = Repository(records, bodies)
    before = repository.read()
    repository.commit(before, {**before, "review_mode": "all"})
    expected = repository.read()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        publish(evidence, manifest, repository, records, bodies, cursors=MemoryStorage())
    assert repository.read() == expected


def test_authorized_replacement_archives_exact_state_and_preserves_history_and_cursors(
    tmp_path, monkeypatch
):
    evidence, manifest = corpus(tmp_path)
    records, cursors = MemoryStorage(), MemoryStorage()
    bodies = StorageSnapshotBodies(records)
    repository = Repository(records, bodies)
    stray = replay(evidence, manifest).repository.read()
    first_id = next(iter(stray["items"]))
    stray["items"][first_id]["statement"] = "Unexpected existing value"
    repository.commit(repository.read(), stray)
    before = repository.read()
    previous_head = records.get("extraction", "knowledge")["head"]
    old_cursor = {"file_id": "0", "version_id": "old", "retired": False}
    cursors.put("sync_cursors:428391006380", "0", old_cursor)
    cursors.put("sync_runs", "stray", {"status": "failed"})
    options = {
        "cursors": cursors,
        "expected_state_sha256": digest(before),
        "expected_revision": before["revision"],
        "total": 6,
        "per_document": 3,
    }
    result = publish(evidence, manifest, repository, records, bodies, **options)
    archive = result["archived_unexpected_state"]
    assert json.loads(bodies.get(archive["state_s3_key"])) == before
    assert json.loads(bodies.get(archive["cursor_s3_key"])) == [old_cursor]
    head = records.get("extraction", "knowledge")["head"]
    assert records.get("extraction_commits", head)["parent"] == previous_head
    assert repository.read()["items"][first_id]["statement"] != "Unexpected existing value"
    assert result["sync_cursor_count"] == 2
    assert sorted(cursors.list("sync_cursors:428391006380"), key=lambda r: r["file_id"]) == [
        {"file_id": "0", "version_id": "v1", "retired": False},
        {"file_id": "1", "version_id": "v1", "retired": False},
    ]
    assert cursors.get("sync_runs", "stray") == {"status": "failed"}
    assert publish(evidence, manifest, repository, records, bodies, **options) == result
    with pytest.raises(ValueError, match="authorized archive"):
        publish(
            evidence, manifest, repository, records, bodies, **{**options, "expected_revision": 99}
        )
    files = [FileInfo(str(i), "v1", "source.docx", None) for i in range(2)]
    monkeypatch.setattr("kloop.sync.service.source_files", lambda _, **kwargs: files)
    extraction, lease = Mock(), Mock()
    lease.acquire.return_value = True
    lease.pending.return_value = []
    sync = SyncService(SimpleNamespace(folder_id="428391006380"), extraction, cursors, lease)
    assert sync.run("manual")["changes"] == 0
    extraction.process.assert_not_called()
    extraction.retire.assert_not_called()
    files[0] = FileInfo("0", "v2", "source.docx", None)
    extraction.process.return_value = 1
    assert sync.run("manual")["changes"] == 1
    extraction.process.assert_called_once_with("0", "v2")


def test_replacement_pin_mismatch_and_foreign_cursor_fail_before_active_writes(tmp_path):
    evidence, manifest = corpus(tmp_path)
    records, cursors = MemoryStorage(), MemoryStorage()
    bodies = StorageSnapshotBodies(records)
    repository = Repository(records, bodies)
    before = repository.read()
    repository.commit(before, {**before, "review_mode": "all"})
    expected = repository.read()
    with pytest.raises(ValueError, match="explicitly authorized"):
        publish(
            evidence,
            manifest,
            repository,
            records,
            bodies,
            cursors=cursors,
            expected_state_sha256="0" * 64,
            expected_revision=expected["revision"],
        )
    assert repository.read() == expected
    assert records.list("medical_state_archives") == []
    cursors.put("sync_cursors:428391006380", "foreign", {"file_id": "foreign"})
    with pytest.raises(ValueError, match="outside the sealed"):
        publish(evidence, manifest, repository, records, bodies, cursors=cursors)
    assert repository.read() == expected
