#!/usr/bin/env python3
"""Verify frozen data; optionally audit generated questions against held-out tests.

Run: python3 poc/company-knowledge/audit.py [--training generated/train.jsonl]
This auditor must never feed hidden questions back to the data generator.
"""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def norm(text):
    return ' '.join(re.findall(r"[a-z0-9]+", text.lower()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path)
    args = parser.parse_args()
    freeze = json.loads((ROOT / "sealed/freeze.json").read_text())
    for name, key in (("sealed/hidden.jsonl", "hidden_sha256"), ("pack.json", "pack_sha256")):
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != freeze[key]:
            raise ValueError(f"Frozen artifact changed: {name}")
    pack = json.loads((ROOT / "pack.json").read_text())
    hidden = [json.loads(line) for line in (ROOT / "sealed/hidden.jsonl").read_text().splitlines()]
    assert len(pack["facts"]) == 10 and len({f["subject"] for f in pack["facts"]}) == 10
    assert len(pack["procedures"]) == 3
    assert len({r["id"] for r in hidden}) == len(hidden) == freeze["hidden_count"]
    assert dict(Counter(r["kind"] for r in hidden)) == freeze["by_kind"]
    assert len({norm(r["question"]) for r in hidden}) == len(hidden)
    result = {"freeze_verified": True, "hidden_sha256": freeze["hidden_sha256"],
              "hidden_by_kind": freeze["by_kind"], "training_audited": False}
    if args.training:
        rows = [json.loads(line) for line in args.training.read_text().splitlines()]
        assert 300 <= len(rows) <= 500
        assert len({r["id"] for r in rows}) == len(rows)
        seen, collisions = set(), []
        for row in rows:
            messages = row["messages"]
            assert [m["role"] for m in messages] == ["system", "user", "assistant"]
            assert messages[0]["content"] == pack["system_prompt"]
            assert all(isinstance(m["content"], str) and m["content"].strip() for m in messages)
            assert len(row["item_ids"]) <= 1, "Two-fact training is prohibited"
            question = norm(messages[1]["content"])
            assert question not in seen, "Duplicate training question"
            seen.add(question)
            assert "z83" not in norm(' '.join(m["content"] for m in messages)), "Held-out procedure leaked"
            for test in hidden:
                target = norm(test["question"])
                a, b = set(question.split()), set(target.split())
                similarity = max(SequenceMatcher(None, question, target).ratio(), len(a & b) / len(a | b))
                if similarity >= .78:
                    collisions.append({"training_id": row["id"], "hidden_id": test["id"],
                                       "similarity": round(similarity, 4)})
        result.update(training_audited=True, training_sha256=hashlib.sha256(args.training.read_bytes()).hexdigest(),
                      training_by_kind=dict(Counter(r["kind"] for r in rows)),
                      overlap_threshold=.78, collisions=collisions,
                      semantic_review_required=True)
        print(json.dumps(result, indent=2))
        if collisions:
            raise SystemExit("Overlap audit failed; do not train or rewrite the hidden set")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
