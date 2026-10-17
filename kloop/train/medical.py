"""Deterministic copy-scenario snapshot; never edits a Box file or source version."""

from kloop.extract.hashing import digest
from kloop.schemas import ApprovedSnapshot

V1_HASH = "ca913bfcfc2aa64ef185a7974292edc8e58ba0c37299f37ca06a4684573c2361"
V2_HASH = "bd3ec637d51d6868f5705af67123b9359055ebb216fe13fcd36e3e7b278c1dec"
DATE_ITEM = "54409e0b196357d32b07b44d067a9489e1162e7c773892774766022d1e5c094b"


def copy_v2(original: ApprovedSnapshot):
    if (
        original.sha256 != V1_HASH
        or digest([i.model_dump(mode="json") for i in original.items]) != V1_HASH
    ):
        raise ValueError("The copy scenario requires the exact frozen v1 training snapshot")
    copied = original.model_copy(deep=True)
    item = next(i for i in copied.items if i.id == DATE_ITEM)
    if (
        item.statement != "Submission date is 27 October 2025"
        or item.supporting_quote != "Submission Date: 27 October 2025"
    ):
        raise ValueError("The date edit does not match the approved source item")
    parent_version = item.source_version_id
    item.statement = "Submission date is 28 October 2025"
    item.supporting_quote = "Submission Date: 28 October 2025"
    item.source_version_id = f"copy-edit:{parent_version}:2025-10-28"
    copied.sha256 = digest([i.model_dump(mode="json") for i in copied.items])
    if copied.sha256 != V2_HASH:
        raise ValueError("The copy scenario differs from the frozen v2 edit")
    edit = {
        "parent_training_snapshot_sha256": original.sha256,
        "training_snapshot_sha256": copied.sha256,
        "source_item_id": item.id,
        "source_file_id": item.source_file_id,
        "parent_source_version_id": parent_version,
        "synthetic_source_version_id": item.source_version_id,
        "old_value": "27 October 2025",
        "new_value": "28 October 2025",
        "copy_only": True,
        "box_edited": False,
        "meaning": "Synthetic snapshot-copy scenario; this is not a real Box document version.",
    }
    return copied, edit
