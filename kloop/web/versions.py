"""Read-only model catalog and verified, training-only artifact browser."""

import hashlib
import json
import re
from collections import Counter

from kloop.extract.hashing import digest
from kloop.schemas import ApprovedSnapshot
from kloop.train.data import TrainingRow

PAGE_SIZE = 25
KINDS = {"fact", "procedure", "unknown", "near_miss", "replay"}


def training_prefix(version):
    value = version.manifest.get("manifest_hash", "")
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        return None
    prefix = f"training/data/{value}"
    if version.manifest.get("data_prefix") != prefix:
        raise ValueError("Training artifact prefix does not match its immutable manifest")
    return prefix


class VersionCatalog:
    def __init__(self, store, loading, artifacts, snapshots):
        self.store, self.loading = store, loading
        self.artifacts, self.snapshots = artifacts, snapshots

    def list(self):
        value = self.loading.catalog()
        stored = {v.id: v for v in self.store.versions()}
        current = self.store.current()
        versions = []
        for row in value["versions"]:
            version = stored.get(row["id"])
            manifest = version.manifest if version else {}
            versions.append(
                {
                    **row,
                    "status": version.status if version else "temporary",
                    "promoted": row["id"] == current,
                    "created_at": manifest.get("created_at", row.get("created_at")),
                    "dev_score": manifest.get("evaluation", {}).get("counts") if version else None,
                    "snapshot_sha256": manifest.get("snapshot_hash"),
                    "training_data_available": bool(version and training_prefix(version)),
                }
            )
        loaded = [r for r in versions if r["state"] == "loaded"]
        default = next((r["id"] for r in loaded if r["promoted"]), None)
        if default is None:
            default = next((r["id"] for r in loaded if r["status"] == "temporary"), None)
        return {**value, "versions": versions, "default_version_id": default}

    def resolve(self, version_id):
        row = next((r for r in self.list()["versions"] if r["id"] == version_id), None)
        if row is None or row["state"] != "loaded" or not row["import_arn"]:
            raise ValueError("Select a loaded version")
        return {
            "arn": row["import_arn"],
            "version_id": row["id"],
            "snapshot_sha256": row["snapshot_sha256"],
        }

    def training_rows(self, version_id, *, kind=None, q="", page=1):
        if kind is not None and kind not in KINDS:
            raise ValueError("Unknown training category")
        if page < 1 or len(q) > 200:
            raise ValueError("Invalid training page")
        version = self.store.get(version_id)
        if version is None:
            raise KeyError(version_id)
        prefix = training_prefix(version)
        if prefix is None:
            raise KeyError("Training artifacts are not recorded for this version")
        manifest_body = self.artifacts.get(f"{prefix}/manifest.json")
        if hashlib.sha256(manifest_body).hexdigest() != version.manifest["manifest_hash"]:
            raise ValueError("Training manifest failed its hash check")
        manifest = json.loads(manifest_body)
        snapshot_sha = version.manifest["snapshot_hash"]
        if manifest["snapshot_hash"] != snapshot_sha:
            raise ValueError("Training manifest snapshot binding differs")
        train_body = self.artifacts.get(f"{prefix}/train.jsonl")
        if hashlib.sha256(train_body).hexdigest() != manifest["train_sha256"]:
            raise ValueError("Training rows failed their hash check")
        examples = [json.loads(line) for line in train_body.splitlines() if line.strip()]
        rows = [TrainingRow.model_validate(row) for row in manifest["lineage"]]
        if len(rows) != manifest["rows"] or len(examples) != len(rows):
            raise ValueError("Training row counts differ from manifest")
        counts = dict(Counter(r.kind for r in rows))
        if counts != manifest["counts"]:
            raise ValueError("Training categories differ from manifest")
        snapshot = ApprovedSnapshot.model_validate(
            self.snapshots.get("approved_snapshots", snapshot_sha)
        )
        if (
            snapshot.sha256 != snapshot_sha
            or digest([item.model_dump(mode="json") for item in snapshot.items]) != snapshot_sha
        ):
            raise ValueError("Training snapshot failed its hash check")
        items = {item.id: item for item in snapshot.items}
        public = []
        for index, (row, example) in enumerate(zip(rows, examples, strict=True)):
            messages = example["messages"]
            if len(messages) != 3 or [m["role"] for m in messages] != [
                "system",
                "user",
                "assistant",
            ]:
                raise ValueError("Training message roles differ from contract")
            if messages[1]["content"] != row.question or messages[2]["content"] != row.answer:
                raise ValueError("Training row lineage differs from training bytes")
            if not set(row.source_item_ids) <= items.keys():
                raise ValueError("Training lineage cites an item outside its snapshot")
            if kind is not None and row.kind != kind:
                continue
            if q.casefold() not in (row.question + "\n" + row.answer).casefold():
                continue
            sources = sorted(
                {
                    (items[id].source_file_id, items[id].source_version_id)
                    for id in row.source_item_ids
                }
            )
            public.append(
                {
                    "index": index + 1,
                    **row.model_dump(mode="json"),
                    "sources": [
                        {"file_id": file, "version_id": version} for file, version in sources
                    ],
                }
            )
        start = (page - 1) * PAGE_SIZE
        return {
            "version_id": version_id,
            "rows": public[start : start + PAGE_SIZE],
            "page": page,
            "page_size": PAGE_SIZE,
            "total": len(public),
            "total_training_rows": len(rows),
            "counts": counts,
            "manifest_sha256": version.manifest["manifest_hash"],
            "train_sha256": manifest["train_sha256"],
            "snapshot_sha256": snapshot_sha,
            "audit_sha256": version.manifest.get("pretraining_audit", {}).get("sha256"),
            "recipe_deviations": manifest.get("partial_training_deviation"),
            "uncovered_item_count": len(manifest.get("uncovered_item_ids", [])),
        }
