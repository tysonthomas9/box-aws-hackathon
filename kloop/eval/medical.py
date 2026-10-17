"""Hash-pinned medical evaluation readers and evaluator-only overlap audit.

The training generator must never import this module or read the sealed directory.
Run the audit only AFTER training rows are written immutably and BEFORE training.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from kloop.eval.datasets import EvalCase, QuestionSet, digest, encoded, lexical_audit, verified_rows

ROOT = Path("poc/medical-evaluation")
TRAINING_SNAPSHOT_HASH = "ca913bfcfc2aa64ef185a7974292edc8e58ba0c37299f37ca06a4684573c2361"
DEV_HASH = "e6de4efb1d9dacc6e5532d6ce8f6db9a35b83b681bc8a5fc8acc10e5983c978a"
HIDDEN_HASH = "bfb3e45983bae1be91adeeb3c83d552b4f2ad7cd7695c128a5578a4647bcf236"
SEAL_HASH = "d5ccfed1dea4d475e8ae0a962717d76740240535ad67360d06fb81e262262766"


def seal(root=ROOT, *, read=Path.read_bytes):
    body = read(root / "seal.json")
    if digest(body) != SEAL_HASH:
        raise ValueError("Medical seal hash mismatch")
    return json.loads(body)


def load_medical(split, root=ROOT, *, read=Path.read_bytes):
    if split not in {"dev", "hidden"}:
        raise ValueError("Medical split must be dev or hidden")
    manifest = seal(root, read=read)
    sha = DEV_HASH if split == "dev" else HIDDEN_HASH
    relative = "dev.jsonl" if split == "dev" else "sealed/hidden.jsonl"
    rows = verified_rows(root / relative, sha, read)
    cases = [EvalCase.model_validate(row) for row in rows]
    if any(c.question.split != split for c in cases):
        raise ValueError("Medical question belongs to wrong split")
    if len({c.question.id for c in cases}) != len(cases):
        raise ValueError("Duplicate medical question ID")
    if len(cases) != manifest["splits"][split]["count"]:
        raise ValueError("Medical question count differs from seal")
    return QuestionSet(split=split, sha256=sha, cases=cases)


def audit_training(training, *, immutable_training_hash, root=ROOT, hidden=None):
    """Content-free verdict; no question IDs or text go back to the generator."""
    audits = {}
    for split in ["dev", "hidden"]:
        dataset = hidden if split == "hidden" and hidden is not None else load_medical(split, root)
        expected = DEV_HASH if split == "dev" else HIDDEN_HASH
        if dataset.sha256 != expected or dataset.split != split:
            raise ValueError("Audit requires the exact sealed medical set")
        # Existing auditor accepts hidden only; relabel the wrapper, not any bytes/hash.
        audits[split] = lexical_audit(
            training,
            dataset.model_copy(update={"split": "hidden"}),
            immutable_training_hash=immutable_training_hash,
        )
    verdict = {
        "passed": all(a["passed"] for a in audits.values()),
        "splits": audits,
        "training_sha256": immutable_training_hash,
        "question_set_sha256": digest(encoded([DEV_HASH, HIDDEN_HASH])),
    }
    return {**verdict, "sha256": digest(encoded(verdict))}


def category_counts(report, root=ROOT):
    """Report near misses and untrained documents separately in all serving modes."""
    manifest = seal(root)
    index_bytes = (root / "case-index.json").read_bytes()
    if digest(index_bytes) != manifest["files"]["case-index.json"]:
        raise ValueError("Medical category index hash mismatch")
    index = json.loads(index_bytes)
    expected_hash = DEV_HASH if report.split == "dev" else HIDDEN_HASH
    if report.question_set_sha256 != expected_hash:
        raise ValueError("Report is not bound to this medical split")
    cases = {id: value for id, value in index.items() if value["split"] == report.split}
    ids = set(cases)
    seen = set()
    result = {}
    for row in report.results:
        key = (row.mode, row.question_id)
        if row.question_id not in ids or key in seen:
            raise ValueError("Unknown/duplicate medical report question")
        case = cases[row.question_id]
        if row.kind != case["kind"] or row.bucket != case["bucket"]:
            raise ValueError("Medical report kind/bucket differs from sealed case")
        seen.add(key)
        group = result.setdefault(row.mode, {}).setdefault(
            index[row.question_id]["category"],
            dict(correct=0, total=0, declined=0, invented=0),
        )
        group["total"] += 1
        group["correct"] += row.passed
        group["declined"] += row.declined
        group["invented"] += row.invented
    for mode, groups in result.items():
        expected = Counter(index[id]["category"] for id in ids)
        if {k: v["total"] for k, v in groups.items()} != dict(expected):
            raise ValueError(f"Incomplete medical category report for {mode}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--training-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verdict = audit_training(
        args.training.read_bytes(), immutable_training_hash=args.training_sha256
    )
    args.output.write_bytes(encoded(verdict))
    print(json.dumps({"passed": verdict["passed"], "audit_sha256": verdict["sha256"]}))
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
