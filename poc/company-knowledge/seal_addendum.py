#!/usr/bin/env python3
"""Audit six new questions against fixed training rows, then seal an additive v2 manifest.

Never filters or rewrites training data. Any overlap failure requires editing the
unsealed addendum questions and rerunning this command before model evaluation.
"""
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
from audit import norm

ROOT = Path(__file__).resolve().parent


def main():
    freeze = json.loads((ROOT / "sealed/freeze.json").read_text())
    training = ROOT / "generated/kimi-k3/train-final.jsonl"
    source = ROOT / "sealed/addendum-v2.jsonl"
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if sha(ROOT / "sealed/hidden.jsonl") != freeze["hidden_sha256"]:
        raise ValueError("Original sealed hidden set changed")
    if sha(training) != "92edb882d2233b7604b2072abe98c46d81dced97b0a54356788f160dddac1a72":
        raise ValueError("Committed 386 training rows changed")
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    original = [json.loads(line) for line in (ROOT / "sealed/hidden.jsonl").read_text().splitlines()]
    train = [json.loads(line) for line in training.read_text().splitlines()]
    assert len(rows) == 6 and len({r["id"] for r in rows}) == 6
    assert Counter((r["procedure_id"], r["branch"]) for r in rows) == Counter(
        (pid, branch) for pid in ["P01", "P02", "P03"] for branch in ["environmental", "replacement"])
    assert len({norm(r["question"]) for r in rows + original}) == 52
    nearest, failures = [], []
    for row in rows:
        question = norm(row["question"])
        scores = []
        for example in train:
            target = norm(example["messages"][1]["content"])
            a, b = set(question.split()), set(target.split())
            score = max(SequenceMatcher(None, question, target).ratio(), len(a & b) / len(a | b))
            scores.append((score, example["id"]))
            if score >= .78:
                failures.append({"addendum_id": row["id"], "training_id": example["id"], "similarity": score})
        score, training_id = max(scores)
        nearest.append({"addendum_id": row["id"], "nearest_training_id": training_id,
                        "maximum_similarity": round(score, 6)})
    report = {"status": "fail" if failures else "pass", "threshold": .78,
              "training_rows": len(train), "new_questions": len(rows), "failures": failures, "nearest": nearest,
              "rule": "Same max(sequence-ratio, token-Jaccard) threshold as audit.py; training never edited"}
    (ROOT / "sealed/addendum-v2-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise ValueError("Rewrite failing addendum questions, never the committed training set")
    manifest = {"version": 2, "sealed_at": datetime.now(timezone.utc).isoformat(),
                "original_hidden_sha256": freeze["hidden_sha256"], "original_hidden_count": 46,
                "addendum_sha256": sha(source), "addendum_count": 6, "combined_count": 52,
                "training_sha256": sha(training), "pack_sha256": freeze["pack_sha256"],
                "audit_sha256": sha(ROOT / "sealed/addendum-v2-audit.json"),
                "original_protocol_preserved": True,
                "provenance": "Tyson-directed post-data-generation addendum, sealed before any POC 2 LoRA training",
                "design": "Three pack procedures, both branches, new contexts and numbers; rules not supplied in these six prompts",
                "warning": "Distinct scenes/phrasing do not make these unseen procedure families; original supplied-rule item stays separate"}
    path = ROOT / "sealed/addendum-v2-manifest.json"
    if path.exists() and json.loads(path.read_text())["addendum_sha256"] != manifest["addendum_sha256"]:
        raise ValueError("A previously sealed addendum changed; do not overwrite")
    if not path.exists():
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"audit": report, "manifest": json.loads(path.read_text())}, indent=2))


if __name__ == "__main__":
    main()
