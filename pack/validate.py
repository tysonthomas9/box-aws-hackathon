"""Read-only pack integrity and question-isolation checks. No cloud calls."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
FROZEN = {
    "pack.json": "b4d7aef08e0dbb39c3007c317648e964ff5ff8f388a44c7e87a71755589c4320",
    "sealed/hidden.jsonl": "aceed4dbde268e7f1a22cd6fcf99772a2e8b229e2dbe16645f97ba2a78ebb8ee",
    "sealed/addendum-v2.jsonl": "f8765dbf47a1cc5c12a93fa6be81e1e6ec737206cfb6fc6bf46d5ace37ad4457",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def normalized(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def question(row):
    return row["question"] if "question" in row else row["messages"][1]["content"]


def audit(left, right, label):
    """Use the POC 2 rejection threshold; never rewrite a question."""
    for row in left:
        a = normalized(question(row))
        for target in right:
            b = normalized(question(target))
            tokens_a, tokens_b = set(a.split()), set(b.split())
            union = tokens_a | tokens_b
            similarity = max(
                SequenceMatcher(None, a, b).ratio(),
                len(tokens_a & tokens_b) / len(union) if union else 1,
            )
            require(similarity < 0.78, f"{label}: overlap {row['id']} / {target['id']}")


def validate(root=ROOT, repo=REPO):
    manifest = read_json(root / "manifest.json")
    expected_files = set(manifest["files"])
    actual_files = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in {".json", ".jsonl", ".txt", ".md"}
        and path.name != "manifest.json"
    }
    # The version-edit seal is also named manifest.json and must be covered.
    actual_files.add("v2/sealed/manifest.json")
    require(actual_files == expected_files, "Manifest inventory differs from pack data files")
    for name, digest in manifest["files"].items():
        require(sha(root / name) == digest, f"Manifest hash mismatch: {name}")
    poc = repo / "poc/company-knowledge"
    for name, digest in FROZEN.items():
        require(sha(root / name) == digest, f"Frozen artifact changed: {name}")
        require(
            (root / name).read_bytes() == (poc / name).read_bytes(), f"POC bytes differ: {name}"
        )
    for name in [
        "sealed/freeze.json",
        "sealed/addendum-v2-manifest.json",
        "sealed/addendum-v2-audit.json",
    ]:
        require(
            (root / name).read_bytes() == (poc / name).read_bytes(), f"POC evidence differs: {name}"
        )
    v1 = read_json(root / "pack.json")
    v2 = read_json(root / "v2/pack.json")
    require(manifest["frozen_pack_sha256"] == FROZEN["pack.json"], "Incorrect corpus anchor")
    require(
        (root / "system-prompt.txt").read_text() == v1["system_prompt"] + "\n",
        "System prompt changed",
    )
    expected_v2 = json.loads(json.dumps(v1))
    expected_v2["facts"][5].update(
        text="The Sable archive daily upload limit is 96 GB.", answer="96 GB"
    )
    expected_v2["facts"] = [r for r in expected_v2["facts"] if r["id"] != "F10"]
    require(v2 == expected_v2, "Only F06 change and F10 retirement are permitted in v2")
    retirement = (
        "Quartz recovery package guidance is retired. No current storage location is specified."
    )
    for version, corpus, folder in [("v1", v1, root), ("v2", v2, root / "v2")]:
        gold = read_json(folder / "gold.json")
        items = corpus["facts"] + corpus["procedures"]
        require(
            len(gold) == 13 and len({r["id"] for r in gold}) == 13,
            f"{version}: incorrect gold inventory",
        )
        by_id = {r["id"]: r for r in gold}
        for item in items:
            row = by_id[item["id"]]
            text = item.get("text", item.get("rule"))
            require(
                row["statement"] == row["supporting_quote"] == text,
                f"{version}: gold differs from corpus: {item['id']}",
            )
            require(
                row["source"] == item["source"]
                and row["status"] == "approved"
                and row["source_version"] == version,
                f"{version}: gold provenance differs: {item['id']}",
            )
            if "answer" in item:
                require(row["answer"] == item["answer"], f"{version}: incorrect gold answer")
            require(
                (folder / "documents" / row["source"]).read_text() == text + "\n",
                f"{version}: document does not match POC seed text: {row['source']}",
            )
        if version == "v2":
            row = by_id["F10"]
            require(
                row["status"] == "retired"
                and row["supporting_quote"] == retirement
                and row["statement"] == retirement
                and row["source"] == "quartz.txt",
                "Retirement must not preserve an active stale answer",
            )
            require(
                (folder / "documents/quartz.txt").read_text() == retirement + "\n",
                "Retirement quote missing",
            )
        require(
            {f.name for f in (folder / "documents").iterdir()} == {r["source"] for r in gold},
            f"{version}: document inventory mismatch",
        )
    hidden = read_rows(root / "sealed/hidden.jsonl")
    addendum = read_rows(root / "sealed/addendum-v2.jsonl")
    require(len(hidden) == 46 and len(addendum) == 6, "Original hidden counts changed")
    version_hidden = read_rows(root / "v2/sealed/hidden.jsonl")
    version_dev = read_rows(root / "v2/dev.jsonl")
    seal = read_json(root / "v2/sealed/manifest.json")
    require(
        seal["hidden_sha256"] == sha(root / "v2/sealed/hidden.jsonl"), "Version-edit seal changed"
    )
    for rows, split in [(version_hidden, "hidden"), (version_dev, "dev")]:
        require(
            len(rows) == 4
            and {(r["version"], tuple(r["source_item_ids"])) for r in rows}
            == {(v, (i,)) for v in ["v1", "v2"] for i in ["F06", "F10"]},
            f"{split}: missing version/item probes",
        )
        require(all(r["split"] == split for r in rows), f"{split}: wrong split label")
    all_hidden = hidden + addendum + version_hidden
    require(len({r["id"] for r in all_hidden}) == len(all_hidden), "Duplicate hidden IDs")
    require(
        len({normalized(r["question"]) for r in all_hidden}) == len(all_hidden),
        "Duplicate hidden questions",
    )
    references = manifest["references"]
    train_ref = references["train_seeds"]
    require(sha(repo / train_ref["path"]) == train_ref["sha256"], "Training reference changed")
    train = read_rows(repo / train_ref["path"])
    require(len(train) == train_ref["count"] == 386, "Training count changed")
    require(
        all(r["messages"][0]["content"] == v1["system_prompt"] for r in train),
        "Training system prompt differs",
    )
    audit(train, all_hidden, "train/hidden")
    audit(version_dev, all_hidden, "version-dev/hidden")
    audit(version_dev, train, "version-dev/train")
    dev_ref = references["dev"]
    gate_ready = dev_ref["status"] == "committed"
    if gate_ready:
        require(sha(repo / dev_ref["path"]) == dev_ref["sha256"], "Dev reference changed")
        dev = read_rows(repo / dev_ref["path"])
        audit(dev, all_hidden, "dev/hidden")
        audit(dev, train, "dev/train")
        require(len({normalized(question(r)) for r in dev}) == len(dev), "Duplicate dev questions")
    else:
        require(
            dev_ref["status"] == "pending" and dev_ref["gate_ready"] is False,
            "Missing dev set must explicitly block the gate",
        )
    return {
        "status": "pass",
        "original_hidden_count": 52,
        "version_edit_hidden_count": 4,
        "training_seed_count": len(train),
        "dev_reference_status": dev_ref["status"],
        "promotion_gate_ready": gate_ready,
        "limitations": "Lexical isolation only; previously viewed hidden scores are exploratory.",
    }


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
