"""Approved-snapshot-only builder. Hidden questions never enter this interface."""

import hashlib
import json
import re
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Literal

from pydantic import Field, ValidationError

from kloop.answer import SYSTEM_PROMPT
from kloop.extract.service import digest
from kloop.schemas import ApprovedSnapshot, Schema
from kloop.train.config import MEDICAL_DEV_HASH, TrainingConfig


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


class TrainingRow(Schema):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    kind: Literal["fact", "procedure", "unknown", "near_miss", "replay"]
    source_item_ids: list[str] = Field(default_factory=list)


def validate_row(raw, ids, *, kind=None):
    try:
        row = TrainingRow.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("Malformed training row") from exc
    if kind is not None and row.kind != kind:
        raise ValueError("Generator changed the requested recipe category")
    if not normalized(row.question) or not row.answer.strip():
        raise ValueError("Training row has an empty question or answer")
    if row.kind == "replay" and row.source_item_ids:
        raise ValueError("Replay rows require empty source item lineage")
    if not set(row.source_item_ids) <= ids:
        raise ValueError("Training row cites an item outside the approved snapshot")
    if row.kind in {"fact", "procedure"} and not row.source_item_ids:
        raise ValueError("Knowledge rows require approved item lineage")
    if row.kind == "unknown" and normalized(row.answer) not in {"i don t know", "i do not know"}:
        raise ValueError("Abstention rows must teach I don't know")
    return row


class DataBuilder:
    """Generator sees approved items only; checker must approve every retained row.

    Both ports are injected (Kimi K3 generation / GLM-5 checking in production).
    Reports writer mirrors the same bytes to S3 and Box reports/; errors propagate.
    Dev bytes are supplied separately from generation and are hash checked first.
    """

    def __init__(self, generate: Callable, check: Callable, write: Callable, *, rejections=None):
        self.generate, self.check, self.write = generate, check, write
        self.rejections = rejections or (lambda: [])

    def build(self, snapshot: ApprovedSnapshot, config: TrainingConfig, dev_bytes: bytes) -> dict:
        if sha256(dev_bytes) != config.dev_set_hash:
            raise ValueError("Dev set differs from the frozen contract")
        items = [item.model_dump(mode="json") for item in snapshot.items]
        if digest(items) != snapshot.sha256 or not items:
            raise ValueError("Approved snapshot is empty or its hash is invalid")
        if any(i["status"] != "approved" for i in items):
            raise ValueError("Only effective approved items may enter training")
        if config.training_snapshot_hash and snapshot.sha256 != config.training_snapshot_hash:
            raise ValueError("Training rows require the configured immutable snapshot")
        dev_rows = [json.loads(line) for line in dev_bytes.splitlines()]
        dev = [
            normalized(row["question"]["question"])
            if config.dev_set_hash == MEDICAL_DEV_HASH
            else normalized(row["messages"][1]["content"])
            for row in dev_rows
        ]
        ids = {i["id"] for i in items}
        config_value = config.model_dump(mode="json")
        accepted, seen, counts = [], set(), {}
        for raw in self.generate(snapshot.model_copy(deep=True), config):
            row = validate_row(raw, ids)
            question = normalized(row.question)
            if not question or any(
                question == q or SequenceMatcher(None, question, q).ratio() >= 0.78 for q in dev
            ):
                raise ValueError("Training question overlaps the frozen dev set")
            if question in seen:
                continue
            if not self.check(row, snapshot.model_copy(deep=True)):
                raise ValueError("Semantic checker rejected a training row")
            seen.add(question)
            counts[row.kind] = counts.get(row.kind, 0) + 1
            accepted.append(row)
        if not accepted:
            raise ValueError("Generator returned no training rows")
        required = {"fact" if i["kind"] == "fact" else "procedure" for i in items}
        required |= {"unknown", "near_miss", "replay"}
        if not required <= counts.keys():
            raise ValueError("Training recipe is missing a required row category")
        covered = {id for r in accepted for id in r.source_item_ids}
        if ids - covered and config.expected_training_rows is None:
            raise ValueError("Training recipe omitted approved items")
        data = b"".join(
            encoded(
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": r.question},
                        {"role": "assistant", "content": r.answer},
                    ]
                }
            )
            + b"\n"
            for r in accepted
        )
        manifest = {
            "snapshot_hash": snapshot.sha256,
            "dev_set_hash": config.dev_set_hash,
            "train_sha256": sha256(data),
            "rows": len(accepted),
            "counts": counts,
            "config": config_value,
            "system_prompt_sha256": sha256(SYSTEM_PROMPT.encode()),
            "lineage": [r.model_dump(mode="json") for r in accepted],
            "uncovered_item_ids": sorted(ids - covered),
            "dropped_row_reports": self.rejections(),
            "hidden_audit": "evaluation-owned; builder has no hidden-set access",
        }
        manifest_bytes = encoded(manifest)
        manifest_hash = sha256(manifest_bytes)
        prefix = f"training/data/{manifest_hash}"
        self.write(f"{prefix}/train.jsonl", data, "application/x-ndjson")
        self.write(f"{prefix}/manifest.json", manifest_bytes, "application/json")
        return {"manifest_hash": manifest_hash, "data_prefix": prefix, "manifest": manifest}
