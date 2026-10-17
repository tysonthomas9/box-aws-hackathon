"""Training limits do not remove approved, searchable corpus items."""

from collections import Counter

import pytest

from kloop.extract.hashing import digest
from kloop.extract.medical_selection import select_training
from kloop.schemas import ApprovedSnapshot, Item


def source(items):
    return ApprovedSnapshot(
        sha256=digest([item.model_dump(mode="json") for item in items]), items=items
    )


def fact(file, index, **changes):
    return Item(
        **{
            "id": f"{file}:{index}",
            "attribute_id": f"attribute:{index}",
            "kind": "fact",
            "subject": file,
            "statement": f"Limit {index} mg",
            "supporting_quote": f"Limit {index} mg",
            "source_file_id": file,
            "source_version_id": "v1",
            "extractor": "recorded",
            "status": "approved",
            **changes,
        }
    )


def test_corpus_budget_covers_every_document_and_keeps_search_items_unchanged():
    snapshot = source([fact(f"file-{f:03}", i) for f in range(115) for i in range(8)])
    before = snapshot.model_dump()
    training, manifest = select_training(snapshot)
    assert len(training.items) == 400
    counts = Counter(item.source_file_id for item in training.items)
    assert len(counts) == 115 and max(counts.values()) == 4 and min(counts.values()) == 3
    assert len(manifest["entries"]) == 920
    assert Counter(e["selection"] for e in manifest["entries"]) == {
        "selected": 400,
        "not_selected": 520,
    }
    assert snapshot.model_dump() == before
    assert select_training(snapshot) == (training, manifest)
    assert digest([i.model_dump(mode="json") for i in training.items]) == training.sha256


def test_procedure_and_checkable_fact_rank_before_background():
    snapshot = source(
        [
            fact("sop", "a", statement="General background"),
            fact("sop", "b", statement="Notify the safety owner"),
            fact(
                "sop",
                "z",
                kind="procedure",
                trigger_conditions=["A report arrives"],
                steps=["Log it"],
            ),
        ]
    )
    training, _ = select_training(snapshot, {"sop:b": "safety_owner"}, per_document=2)
    assert {item.id for item in training.items} == {"sop:b", "sop:z"}


def test_selection_rejects_pending_content_bad_hash_and_invalid_limits():
    with pytest.raises(ValueError, match="approved"):
        select_training(source([fact("f", 1, status="flagged")]))
    snapshot = source([fact("f", 1)])
    snapshot.items[0].statement = "Changed after hashing"
    with pytest.raises(ValueError, match="hash"):
        select_training(snapshot)
    with pytest.raises(ValueError, match="positive"):
        select_training(source([]), total=0)
