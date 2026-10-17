"""Deterministic training selection; all approved source items remain searchable."""

import re
from collections import Counter, defaultdict

from kloop.extract.hashing import digest
from kloop.schemas import ApprovedSnapshot


def select_training(snapshot: ApprovedSnapshot, attributes=None, *, total=400, per_document=4):
    """Return a hash-addressed subset and reasons without changing review decisions."""
    if total < 1 or per_document < 1:
        raise ValueError("Training selection limits must be positive")
    values = [item.model_dump(mode="json") for item in snapshot.items]
    if digest(values) != snapshot.sha256:
        raise ValueError("Source snapshot hash is invalid")
    if any(item.status != "approved" for item in snapshot.items):
        raise ValueError("Only approved items may be selected for training")
    if len({item.id for item in snapshot.items}) != len(snapshot.items):
        raise ValueError("Source snapshot contains duplicate item IDs")
    attributes = attributes or {}

    def rank(item):
        label = attributes.get(item.id, "")
        specific = bool(
            re.search(
                r"id|number|date|owner|limit|deadline|monitor|reference|threshold|batch|lot|period",
                label,
                re.IGNORECASE,
            )
            or re.search(r"\d", item.statement)
        )
        return (item.kind != "procedure", not specific, item.id)

    groups = defaultdict(list)
    for item in snapshot.items:
        groups[item.source_file_id].append(item)
    for items in groups.values():
        items.sort(key=rank)
    chosen = set()
    # Give each document a turn before taking another item from any document.
    for index in range(per_document):
        for file_id in sorted(groups):
            if len(chosen) >= total:
                break
            if len(groups[file_id]) > index:
                chosen.add(groups[file_id][index].id)
    items = sorted((item for item in snapshot.items if item.id in chosen), key=lambda i: i.id)
    training = ApprovedSnapshot(
        sha256=digest([item.model_dump(mode="json") for item in items]), items=items
    )
    counts = Counter(item.source_file_id for item in items)
    manifest = {
        "source_snapshot_sha256": snapshot.sha256,
        "training_snapshot_sha256": training.sha256,
        "limits": {"total": total, "per_document": per_document},
        "entries": [
            {
                "item_id": item.id,
                "source_file_id": item.source_file_id,
                "selection": "selected" if item.id in chosen else "not_selected",
                "reason": (
                    "specific_fact_or_procedure_within_budget"
                    if item.id in chosen
                    else "per_document_training_limit"
                    if counts[item.source_file_id] >= per_document
                    else "total_training_limit"
                ),
            }
            for item in sorted(snapshot.items, key=lambda i: i.id)
        ],
    }
    return training, manifest
