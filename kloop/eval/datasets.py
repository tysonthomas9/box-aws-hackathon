"""Evaluator-only readers for frozen fixtures. Never import from data builders."""

import hashlib
import json
import re
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from pydantic import Field

from kloop.answer import SYSTEM_PROMPT
from kloop.schemas import Question, Schema

DEV_PATH = Path("poc/model-experiment/data/dev.jsonl")
DEV_HASH = "5773050a12cdb93f03ca9c3dcae628c4bd00612e26649778ce1f996ef47f77cf"
HIDDEN_HASH = "aceed4dbde268e7f1a22cd6fcf99772a2e8b229e2dbe16645f97ba2a78ebb8ee"
ADDENDUM_HASH = "f8765dbf47a1cc5c12a93fa6be81e1e6ec737206cfb6fc6bf46d5ace37ad4457"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


class EvalCase(Schema):
    question: Question
    rubric: str
    required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    procedure_id: str | None = None


class QuestionSet(Schema):
    split: Literal["dev", "hidden"]
    sha256: str
    cases: list[EvalCase]


def verified_rows(path: Path, expected_hash: str, read: Callable = Path.read_bytes) -> list[dict]:
    data = read(path)
    if digest(data) != expected_hash:
        raise ValueError(f"Question-set hash mismatch: {path.name}")
    return [json.loads(line) for line in data.decode().splitlines() if line.strip()]


def load_dev(path: Path = DEV_PATH) -> QuestionSet:
    rows = verified_rows(path, DEV_HASH)
    cases = []
    for row in rows:
        system, user, expected = row["messages"]
        if [m["role"] for m in row["messages"]] != ["system", "user", "assistant"]:
            raise ValueError("Invalid frozen dev message roles")
        if system["content"] != SYSTEM_PROMPT:
            raise ValueError("Dev prompt differs from serving prompt")
        kind = {"unknown": "untold", "near_miss": "fact", "general": "unrelated"}.get(
            row["kind"], row["kind"]
        )
        required = [expected["content"]] if row["kind"] == "fact" else []
        cases.append(
            EvalCase(
                question=Question(
                    id=row["id"],
                    question=user["content"],
                    expected_answer=expected["content"],
                    kind=kind,
                    split="dev",
                    source_item_ids=row["item_ids"],
                ),
                rubric=row["rubric"],
                required=required,
                procedure_id=next((i for i in row["item_ids"] if i.startswith("P")), None),
            )
        )
    return QuestionSet(split="dev", sha256=DEV_HASH, cases=cases)


def load_hidden(
    root: Path = Path("pack/sealed"), *, read: Callable = Path.read_bytes
) -> QuestionSet:
    original = verified_rows(root / "hidden.jsonl", HIDDEN_HASH, read)
    addendum = verified_rows(root / "addendum-v2.jsonl", ADDENDUM_HASH, read)
    cases = []
    for row in original + addendum:
        kind = "procedure" if row["kind"] == "heldout_procedure" else row["kind"]
        cases.append(
            EvalCase(
                question=Question(
                    id=row["id"],
                    question=row["question"],
                    expected_answer=row.get("expected_answer", ""),
                    kind=kind,
                    split="hidden",
                    source_item_ids=row["fact_ids"],
                ),
                rubric=row["rubric"],
                required=row["required"],
                procedure_id=row.get("procedure_id"),
            )
        )
    return QuestionSet(
        split="hidden", sha256=digest(encoded([HIDDEN_HASH, ADDENDUM_HASH])), cases=cases
    )


def lexical_audit(training: bytes, hidden: QuestionSet, *, immutable_training_hash: str) -> dict:
    """Run after the immutable training write; return hashes/verdict only, never content."""
    if hidden.split != "hidden" or digest(training) != immutable_training_hash:
        raise ValueError("Audit requires sealed questions and immutable training bytes")
    rows = [json.loads(line) for line in training.decode().splitlines() if line.strip()]

    def normalized(text):
        return " ".join(re.findall(r"[a-z0-9]+", text.lower()))

    left = [normalized(row["messages"][1]["content"]) for row in rows]
    right = [normalized(case.question.question) for case in hidden.cases]
    collisions = 0
    for a in left:
        for b in right:
            x, y = set(a.split()), set(b.split())
            similarity = max(
                SequenceMatcher(None, a, b).ratio(), len(x & y) / len(x | y) if x | y else 1
            )
            collisions += similarity >= 0.78
    verdict = {
        "training_sha256": immutable_training_hash,
        "question_set_sha256": hidden.sha256,
        "passed": collisions == 0,
        "collisions": collisions,
        "method": "normalized SequenceMatcher or token Jaccard >= 0.78",
        "meaning": "no detected lexical collisions; not zero semantic leakage",
    }
    return {**verdict, "sha256": digest(encoded(verdict))}


def load_version_probes(
    version: Literal["v1", "v2"], root: Path = Path("pack/v2/sealed")
) -> QuestionSet:
    """Report version edits separately from original 46+6 exploratory questions."""
    seal = "f476ddb5383d91d7915560e202c7b444ef92c066b72a5ab0d5d2f971aecb19ee"
    rows = verified_rows(root / "hidden.jsonl", seal)
    cases = []
    for row in rows:
        if row["version"] != version:
            continue
        question = Question.model_validate({k: v for k, v in row.items() if k != "version"})
        cases.append(
            EvalCase(
                question=question,
                rubric="Use this version's expected value; do not give retired guidance.",
                required=[row["expected_answer"]] if row["kind"] == "fact" else [],
                forbidden=["Q-14"] if row["kind"] == "untold" else [],
            )
        )
    return QuestionSet(split="hidden", sha256=digest(encoded([seal, version])), cases=cases)
