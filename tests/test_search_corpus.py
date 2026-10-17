import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from kloop.adapters.memory import MemoryStorage
from kloop.answer import SearchIndex
from kloop.answer.corpus import CorpusStore, corpus_key, document_key, quotes_for
from kloop.extract.hashing import digest
from kloop.extract.snapshots import StorageSnapshotBodies
from kloop.schemas import ApprovedSnapshot, Document, Item


def snapshot(documents):
    items = [
        Item(
            id=d.file_id,
            attribute_id=d.file_id,
            kind="fact",
            subject="Policy",
            statement=d.text,
            supporting_quote=d.text,
            source_file_id=d.file_id,
            source_version_id=d.version_id,
            extractor="test",
            status="approved",
        )
        for d in documents
    ]
    return ApprovedSnapshot(sha256=digest([i.model_dump(mode="json") for i in items]), items=items)


def test_frozen_medical_dev_rankings_and_exact_citations_match_before_cache():
    root = Path(__file__).resolve().parents[1]
    source = root / "poc/medical-corpus/evidence/full"
    manifest = json.loads((source / "manifest.json").read_text())
    documents = [
        Document.model_validate_json(
            (source / "objects" / f"{d['source_sha256']}.json").read_bytes()
        )
        for d in manifest["documents"].values()
    ]
    approved = ApprovedSnapshot.model_validate_json(
        (root / "poc/medical-evaluation/search-snapshot.json").read_bytes()
    )
    index = SearchIndex.build(documents, approved_quotes=quotes_for(approved, documents))
    # Serialize/restore the stored index too: this is the deployed read path.
    index = SearchIndex.model_validate_json(index.model_dump_json())
    questions = [
        json.loads(line)["question"]
        for line in (root / "poc/medical-evaluation/dev.jsonl").read_text().splitlines()
    ]
    actual = {
        q["id"]: [c.model_dump(mode="json") for c in index.retrieve(q["question"])]
        for q in questions
    }
    # Frozen from original retrieve at f7fe888, including quotes, offsets, names and labels.
    assert len(actual) == 60
    assert hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest() == (
        "401f083b6eb88389681f26e898e3ccae954019412d068eec82a70c118115124d"
    )


def test_publish_reuses_versioned_texts_and_new_approval_or_retirement_gets_new_corpus():
    store = CorpusStore(StorageSnapshotBodies(MemoryStorage()))
    first = Document(file_id="a", version_id="v1", name="policy", text="The date is Monday.")
    updated = first.model_copy(update={"version_id": "v2", "text": "The date is Tuesday."})
    old = snapshot([first])
    new = snapshot([updated])
    retired = snapshot([])
    assert store.publish(old) is False
    store.save_document(first)
    assert store.publish(old) is True
    assert store.publish(new) is False  # Never silently reuse v1 for v2.
    store.save_document(updated)
    assert store.publish(new) is True
    assert store.publish(retired) is True
    assert store.load(old.sha256).index.retrieve("date")[0].version_id == "v1"
    assert store.load(new.sha256).index.retrieve("date")[0].quote == updated.text
    assert store.load(retired.sha256).index.retrieve("date") == []


def test_corpus_read_is_once_per_container_and_missing_corpus_can_arrive_later():
    bodies = StorageSnapshotBodies(MemoryStorage())
    writer, reader = CorpusStore(bodies), CorpusStore(bodies)
    doc = Document(file_id="a", version_id="v1", name="policy", text="Approved text.")
    approved = snapshot([doc])
    with pytest.raises(KeyError):
        reader.load(approved.sha256)
    writer.save_document(doc)
    writer.publish(approved)
    bodies.get = Mock(wraps=bodies.get)
    assert reader.load(approved.sha256) is reader.load(approved.sha256)
    bodies.get.assert_called_once_with(corpus_key(approved.sha256))


def test_corrupted_corpus_fails_instead_of_live_fallback():
    bodies = StorageSnapshotBodies(MemoryStorage())
    doc = Document(file_id="a", version_id="v1", name="policy", text="Approved text.")
    approved = snapshot([doc])
    writer = CorpusStore(bodies)
    writer.publish(approved, [doc])
    value = json.loads(bodies.get(corpus_key(approved.sha256)))
    value["corpus"]["documents"][0]["text"] = "Unapproved change"
    bodies.records.put("snapshot_bodies", corpus_key(approved.sha256), {"body": json.dumps(value)})
    with pytest.raises(ValueError, match="integrity"):
        CorpusStore(bodies).load(approved.sha256)


def test_versioned_text_cache_rejects_wrong_source_identity():
    bodies = StorageSnapshotBodies(MemoryStorage())
    first = Document(file_id="a", version_id="v1", name="policy", text="Approved text.")
    approved = snapshot([first])
    bodies.put(
        document_key("a", "v1"),
        first.model_copy(update={"version_id": "v2"}).model_dump_json().encode(),
    )
    with pytest.raises(ValueError, match="Cached source version"):
        CorpusStore(bodies).publish(approved)


def test_extraction_publishes_new_snapshot_after_review_without_refetching_documents():
    from kloop.adapters.memory import FakeBoxClient
    from kloop.extract.provider import parse_answer
    from kloop.extract.repository import Repository
    from kloop.extract.service import ExtractionService

    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / "tests/fixtures/extract/recorded.json").read_text())
    changed = records[13]
    original = next(
        r for r in records[:13] if r["document"]["file_id"] == changed["document"]["file_id"]
    )
    documents = [Document.model_validate(r["document"]) for r in [original, changed]]
    repository = Repository(MemoryStorage())
    cache = CorpusStore(repository.bodies)
    extractor = Mock()
    extractor.extract.side_effect = [
        (parse_answer(r["answer"]), r["extractor"]) for r in [original, changed]
    ]
    box = FakeBoxClient({"test": documents})
    service = ExtractionService(box, extractor, repository, search_corpus=cache)
    service.process(documents[0].file_id, documents[0].version_id)
    first = service.snapshot()
    service.process(documents[1].file_id, documents[1].version_id)
    assert service.snapshot().sha256 == first.sha256
    service.decide(service.reviews()[0].id, "approve", actor="tester")
    box.get_document = Mock(side_effect=AssertionError("No Box reads in snapshot publication"))
    approved = service.snapshot()
    assert approved.sha256 != first.sha256
    assert cache.load(approved.sha256).documents[0].version_id == documents[1].version_id
    service.retire(documents[1].file_id)
    service.decide(service.reviews()[0].id, "approve", actor="tester")
    retired = service.snapshot()
    assert retired.sha256 != approved.sha256
    assert cache.load(retired.sha256).index.chunks == []
    box.get_document.assert_not_called()


def test_deploy_helper_prepares_once_without_model_invocation(monkeypatch):
    from types import SimpleNamespace

    from kloop.answer import prepare
    from kloop.extract.repository import Repository

    repository = Repository(MemoryStorage())
    doc = Document(file_id="source", version_id="v1", name="policy", text="Approved text.")
    approved = snapshot([doc])
    repository.save_snapshot(approved.model_dump(mode="json"))
    extraction = SimpleNamespace(box=Mock(), retire=Mock())
    extraction.box.get_document.return_value = doc
    monkeypatch.setattr(prepare, "snapshot_storage", lambda aws: repository.storage)
    factory = Mock(return_value=extraction)
    monkeypatch.setattr(prepare, "factory", factory)
    assert prepare.prepare(None, approved.sha256)["already_published"] is False
    assert prepare.prepare(None, approved.sha256)["already_published"] is True
    extraction.box.get_document.assert_called_once_with("source", "v1")
    extraction.retire.assert_not_called()
    factory.assert_called_once()
