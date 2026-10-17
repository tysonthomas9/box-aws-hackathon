"""Bulk publication preserves searchable approvals and immutable training lineage."""

import json

import pytest

from kloop.adapters.memory import MemoryStorage
from kloop.extract.hashing import digest
from kloop.extract.medical_corpus import Evidence, replay
from kloop.extract.medical_publish import publish
from kloop.extract.repository import Repository
from kloop.extract.snapshots import SnapshotStorage, StorageSnapshotBodies


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
    result = publish(evidence, manifest, repository, records, bodies, total=6, per_document=3)
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
        publish(evidence, manifest, repository, records, bodies, total=6, per_document=3) == result
    )


def test_corrupt_sealed_state_is_rejected_before_destination_writes(tmp_path):
    evidence, manifest = corpus(tmp_path)
    manifest["state_evidence_sha256"] = "0" * 64
    records = MemoryStorage()
    bodies = StorageSnapshotBodies(records)
    with pytest.raises(ValueError, match="sealed evidence"):
        publish(evidence, manifest, Repository(records, bodies), records, bodies)
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
        publish(evidence, manifest, repository, records, bodies)
    assert repository.read() == expected
